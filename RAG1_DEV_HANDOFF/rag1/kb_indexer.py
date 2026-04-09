"""
Knowledge Base Indexer — Parse PDF → Chunk → Embed → ChromaDB.

Reads RAG1_Knowledge_Base_CXR14_v2.pdf (20 pages, 14 classes) and creates
a structured + embedded ChromaDB collection for hybrid retrieval.
"""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from typing import Any

import chromadb
import fitz  # pymupdf
from openai import OpenAI

from rag1.config import RAG1Config
from rag1.kb_schema import CLASS_INFO, SECTION_TYPES, KBChunk

# Section header patterns (Vietnamese + English from PDF)
_SECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("definition",     re.compile(r"^1\.\s*Định nghĩa\s*/\s*Bệnh học", re.IGNORECASE)),
    ("xray_features",  re.compile(r"^2\.\s*Dấu hiệu X-quang", re.IGNORECASE)),
    ("severity",       re.compile(r"^3\.\s*Phân tầng mức độ nặng", re.IGNORECASE)),
    ("ddx",            re.compile(r"^4\.\s*Chẩn đoán phân biệt", re.IGNORECASE)),
    ("next_steps",     re.compile(r"^5\.\s*Bước tiếp theo", re.IGNORECASE)),
    ("clinical_notes", re.compile(r"^6\.\s*Lưu ý lâm sàng", re.IGNORECASE)),
    ("rag_tags",       re.compile(r"^7\.\s*Từ khoá RAG", re.IGNORECASE)),
    ("references",     re.compile(r"^8\.\s*Tài liệu tham khảo", re.IGNORECASE)),
]

# Class header pattern: "Class 00", "Class 01", etc.
_CLASS_HEADER = re.compile(r"^Class\s+(\d{2})\b", re.IGNORECASE)


def extract_pdf_text(pdf_path: Path) -> str:
    """Extract all text from PDF."""
    doc = fitz.open(str(pdf_path))
    pages = []
    for page in doc:
        pages.append(page.get_text())
    doc.close()
    return "\n".join(pages)


def _find_class_info(class_id: int) -> dict[str, str]:
    """Lookup class info by id."""
    for info in CLASS_INFO:
        if int(info["id"]) == class_id:
            return info
    return {"id": str(class_id), "en": f"Class_{class_id}", "vi": f"Lớp_{class_id}", "icd10": ""}


def _split_into_class_blocks(full_text: str) -> list[tuple[int, str]]:
    """
    Split the full PDF text into blocks per class.
    Returns list of (class_id, block_text).
    """
    lines = full_text.split("\n")
    blocks: list[tuple[int, str]] = []
    current_class_id: int | None = None
    current_lines: list[str] = []

    for line in lines:
        match = _CLASS_HEADER.match(line.strip())
        if match:
            if current_class_id is not None:
                blocks.append((current_class_id, "\n".join(current_lines)))
            current_class_id = int(match.group(1))
            current_lines = [line]
        elif current_class_id is not None:
            current_lines.append(line)

    # Last block
    if current_class_id is not None:
        blocks.append((current_class_id, "\n".join(current_lines)))

    return blocks


def _split_into_sections(block_text: str) -> list[tuple[str, str]]:
    """
    Split a class block into (section_type, content) pairs.
    """
    lines = block_text.split("\n")
    sections: list[tuple[str, str]] = []
    current_section: str | None = None
    current_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        matched_section: str | None = None
        for section_type, pattern in _SECTION_PATTERNS:
            if pattern.match(stripped):
                matched_section = section_type
                break

        if matched_section is not None:
            if current_section is not None and current_lines:
                sections.append((current_section, "\n".join(current_lines).strip()))
            current_section = matched_section
            current_lines = []
        elif current_section is not None:
            current_lines.append(line)

    if current_section is not None and current_lines:
        sections.append((current_section, "\n".join(current_lines).strip()))

    return sections


def _extract_rag_tags(content: str) -> list[str]:
    """Extract pipe-delimited tags from RAG tags section."""
    tags = []
    for part in content.split("|"):
        tag = part.strip()
        if tag and len(tag) > 1:
            tags.append(tag)
    return tags


def _extract_references(content: str) -> list[str]:
    """Extract reference lines."""
    refs = []
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("[") and "]" in line:
            refs.append(line)
    return refs


def parse_kb_chunks(pdf_path: Path) -> list[KBChunk]:
    """
    Parse the knowledge base PDF into structured chunks.

    Returns one KBChunk per class per section (~14 × 8 = ~112 chunks).
    """
    full_text = extract_pdf_text(pdf_path)
    class_blocks = _split_into_class_blocks(full_text)

    if not class_blocks:
        raise ValueError(f"No class blocks found in PDF: {pdf_path}")

    all_chunks: list[KBChunk] = []

    # Collect rag_tags and references per class for cross-referencing
    class_tags: dict[int, list[str]] = {}
    class_refs: dict[int, list[str]] = {}

    # First pass: parse all sections
    parsed_blocks: list[tuple[int, list[tuple[str, str]]]] = []
    for class_id, block_text in class_blocks:
        sections = _split_into_sections(block_text)
        parsed_blocks.append((class_id, sections))
        for section_type, content in sections:
            if section_type == "rag_tags":
                class_tags[class_id] = _extract_rag_tags(content)
            elif section_type == "references":
                class_refs[class_id] = _extract_references(content)

    # Second pass: create KBChunk objects
    for class_id, sections in parsed_blocks:
        info = _find_class_info(class_id)
        tags = class_tags.get(class_id, [])
        refs = class_refs.get(class_id, [])

        for section_type, content in sections:
            if not content.strip():
                continue

            chunk_id = f"KB_{class_id:02d}_{section_type}_001"
            chunk = KBChunk(
                chunk_id=chunk_id,
                class_id=class_id,
                class_name=info["en"],
                class_name_vi=info["vi"],
                icd10=info["icd10"],
                section_type=section_type,
                content=content,
                rag_tags=tags,
                references=refs,
            )
            all_chunks.append(chunk)

    return all_chunks


def _batch_embed(
    client: OpenAI,
    texts: list[str],
    model: str,
    batch_size: int = 20,
) -> list[list[float]]:
    """Embed texts in batches via OpenAI-compatible API."""
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        response = client.embeddings.create(input=batch, model=model)
        for item in response.data:
            all_embeddings.append(item.embedding)
        # Rate limit courtesy
        if i + batch_size < len(texts):
            time.sleep(0.5)
    return all_embeddings


def build_index(config: RAG1Config | None = None) -> tuple[int, Path]:
    """
    Parse PDF → Chunk → Embed → Store in ChromaDB.

    Returns (num_chunks, chroma_persist_dir).
    """
    if config is None:
        config = RAG1Config()
    config.validate()

    print(f"[KB Indexer] Parsing PDF: {config.kb_pdf_path}")
    chunks = parse_kb_chunks(config.kb_pdf_path)
    print(f"[KB Indexer] Parsed {len(chunks)} chunks from {len(set(c.class_id for c in chunks))} classes")

    # Prepare texts for embedding
    embed_texts: list[str] = []
    for chunk in chunks:
        # Rich embedding text: class name + section + content + tags
        parts = [
            f"Class: {chunk.class_name} ({chunk.class_name_vi})",
            f"ICD-10: {chunk.icd10}",
            f"Section: {chunk.section_type}",
            chunk.content,
        ]
        if chunk.rag_tags:
            parts.append(f"Tags: {', '.join(chunk.rag_tags)}")
        embed_texts.append("\n".join(parts))

    # Create OpenAI-compatible client for GitHub Models
    print(f"[KB Indexer] Embedding {len(embed_texts)} chunks with {config.embedding_model}...")
    client = OpenAI(
        base_url=config.api_base_url,
        api_key=config.github_token,
    )
    embeddings = _batch_embed(client, embed_texts, config.embedding_model)
    print(f"[KB Indexer] Got {len(embeddings)} embeddings (dim={len(embeddings[0])})")

    # Store in ChromaDB
    persist_dir = config.chroma_persist_dir
    persist_dir.mkdir(parents=True, exist_ok=True)

    chroma_client = chromadb.PersistentClient(path=str(persist_dir))

    # Delete existing collection if any
    try:
        chroma_client.delete_collection("rag1_kb")
    except Exception:
        pass

    collection = chroma_client.create_collection(
        name="rag1_kb",
        metadata={"hnsw:space": "cosine"},
    )

    # Add all chunks
    ids = [chunk.chunk_id for chunk in chunks]
    documents = [chunk.content for chunk in chunks]
    metadatas = [
        {
            "class_id": chunk.class_id,
            "class_name": chunk.class_name,
            "class_name_vi": chunk.class_name_vi,
            "icd10": chunk.icd10,
            "section_type": chunk.section_type,
            "rag_tags": "|".join(chunk.rag_tags),
        }
        for chunk in chunks
    ]

    collection.add(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas,
    )

    count = collection.count()
    print(f"[KB Indexer] Stored {count} chunks in ChromaDB at {persist_dir}")
    return count, persist_dir


if __name__ == "__main__":
    build_index()
