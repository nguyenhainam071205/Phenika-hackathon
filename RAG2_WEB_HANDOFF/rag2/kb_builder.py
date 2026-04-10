"""
KB Builder — Parse knowledge base markdown files and index into ChromaDB.

Reads from rag2/kb_data/ (L1, L2, L3 layers) and builds a ChromaDB collection.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import chromadb
from openai import OpenAI

from rag2.config import RAG2Config


# Pathology group mapping for metadata
PATHOLOGY_GROUPS = {
    "nhom1_binh_thuong": "normal",
    "nhom2_viem_phoi_tran_dich": "pneumonia_effusion",
    "nhom3_suy_tim": "heart_failure",
    "nhom4_ild_xo_phoi": "ild_fibrosis",
    "nhom5_tran_khi": "pneumothorax",
    "nhom6_not_khoi": "nodule_mass",
}

# Class names associated with each pathology group (for retrieval matching)
GROUP_CLASS_NAMES = {
    "normal": [],
    "pneumonia_effusion": ["Consolidation", "Pleural Effusion", "Infiltration"],
    "heart_failure": ["Cardiomegaly", "Pleural Effusion"],
    "ild_fibrosis": ["ILD", "Pulmonary Fibrosis"],
    "pneumothorax": ["Pneumothorax"],
    "nodule_mass": ["Nodule/Mass", "Lung Opacity"],
}


def _chunk_id(layer: str, filename: str, idx: int) -> str:
    """Generate a deterministic chunk ID."""
    raw = f"{layer}_{filename}_{idx}"
    short_hash = hashlib.md5(raw.encode()).hexdigest()[:8]
    return f"RAG2_{layer}_{short_hash}"


def _read_markdown_file(path: Path) -> str:
    """Read a markdown file."""
    return path.read_text(encoding="utf-8")


def _split_into_chunks(content: str, layer: str) -> list[dict]:
    """
    Split content into chunks based on layer type.

    L1: One template = one chunk (complete report template)
    L2: Split by ## headings (each table/rule section)
    L3: One few-shot pair = one chunk
    """
    chunks = []

    if layer == "L1":
        # Entire template is one chunk
        chunks.append({"content": content, "chunk_type": "report_template"})

    elif layer == "L2":
        # Split by ## headings
        sections = re.split(r"\n(?=## )", content)
        for section in sections:
            section = section.strip()
            if section and len(section) > 50:  # Skip very short sections
                chunks.append({"content": section, "chunk_type": "terminology"})

    elif layer == "L3":
        # Entire few-shot pair is one chunk
        chunks.append({"content": content, "chunk_type": "fewshot_pair"})

    return chunks


def _embed_texts(texts: list[str], config: RAG2Config) -> list[list[float]]:
    """Embed a batch of texts using OpenAI-compatible API."""
    client = OpenAI(
        base_url=config.api_base_url,
        api_key=config.github_token,
    )

    # Batch embed (GitHub Models API supports batch)
    embeddings = []
    batch_size = 16
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        response = client.embeddings.create(
            input=batch,
            model=config.embedding_model,
        )
        for item in response.data:
            embeddings.append(item.embedding)

    return embeddings


def build_index(config: RAG2Config | None = None) -> tuple[int, Path]:
    """
    Build ChromaDB index from KB data files.

    Scans rag2/kb_data/{L1, L2, L3} directories, chunks content,
    embeds with OpenAI, and stores in ChromaDB.

    Returns:
        (num_chunks, persist_dir)
    """
    config = config or RAG2Config()
    config.validate()

    kb_dir = config.kb_data_dir
    persist_dir = config.chroma_persist_dir

    if not kb_dir.exists():
        raise FileNotFoundError(f"KB data directory not found: {kb_dir}")

    # Collect all chunks with metadata
    all_chunks: list[dict] = []

    layer_dirs = {
        "L1": kb_dir / "L1_mau_bao_cao",
        "L2": kb_dir / "L2_ngon_ngu_chuan",
        "L3": kb_dir / "L3_fewshot_pairs",
    }

    for layer, layer_dir in layer_dirs.items():
        if not layer_dir.exists():
            print(f"  [WARN] Layer dir not found: {layer_dir}")
            continue

        for md_file in sorted(layer_dir.glob("*.md")):
            content = _read_markdown_file(md_file)
            file_stem = md_file.stem

            # Determine pathology group from filename
            pathology_group = PATHOLOGY_GROUPS.get(file_stem, "general")

            # Get associated class names
            class_names = GROUP_CLASS_NAMES.get(pathology_group, [])

            # Split into chunks
            raw_chunks = _split_into_chunks(content, layer)

            for idx, chunk_data in enumerate(raw_chunks):
                chunk_id = _chunk_id(layer, file_stem, idx)
                all_chunks.append({
                    "id": chunk_id,
                    "content": chunk_data["content"],
                    "metadata": {
                        "layer": layer,
                        "chunk_type": chunk_data["chunk_type"],
                        "pathology_group": pathology_group,
                        "class_names": "|".join(class_names),  # ChromaDB metadata is flat
                        "source_file": md_file.name,
                    },
                })

    if not all_chunks:
        raise ValueError("No chunks found in KB data directory")

    print(f"  [KB] Found {len(all_chunks)} chunks across {len(layer_dirs)} layers")

    # Embed all chunks
    print(f"  [KB] Embedding {len(all_chunks)} chunks...")
    texts = [c["content"] for c in all_chunks]
    embeddings = _embed_texts(texts, config)
    print(f"  [KB] Embedding complete")

    # Create/recreate ChromaDB collection
    persist_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(persist_dir))

    # Delete existing collection if exists
    try:
        client.delete_collection("rag2_kb")
    except Exception:
        pass  # Collection may not exist yet

    collection = client.create_collection(
        name="rag2_kb",
        metadata={"hnsw:space": "cosine"},
    )

    # Add all chunks
    collection.add(
        ids=[c["id"] for c in all_chunks],
        embeddings=embeddings,
        documents=[c["content"] for c in all_chunks],
        metadatas=[c["metadata"] for c in all_chunks],
    )

    print(f"  [KB] Indexed {len(all_chunks)} chunks to {persist_dir}")
    return len(all_chunks), persist_dir
