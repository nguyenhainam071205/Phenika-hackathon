"""
Hybrid retriever for RAG1.

Structured sections are always preserved. The caller's top_k only limits
how many semantic extras are appended.
"""

from __future__ import annotations

import time
from typing import Any

import chromadb
from openai import OpenAI

from rag1.config import RAG1Config
from rag1.kb_schema import RetrievedChunk, SECTION_TYPES
from rag1.runtime_support import JsonDiskCache, is_transient_api_error, stable_hash


class HybridRetriever:
    SECTION_PRIORITY: dict[str, float] = {
        "severity": 1.0,
        "xray_features": 0.95,
        "ddx": 0.9,
        "clinical_notes": 0.85,
        "next_steps": 0.8,
        "definition": 0.7,
        "rag_tags": 0.5,
        "references": 0.3,
    }

    def __init__(self, config: RAG1Config) -> None:
        self.config = config
        self._chroma_client = chromadb.PersistentClient(path=str(config.chroma_persist_dir))
        self._collection = self._chroma_client.get_collection("rag1_kb")
        self._openai = None if config.safe_mode else OpenAI(base_url=config.api_base_url, api_key=config.github_token)
        self._cache = JsonDiskCache(config.cache_dir)

    def _embed_query(self, text: str) -> list[float]:
        if self._openai is None:
            raise RuntimeError("safe_mode_enabled")

        last_exc: Exception | None = None
        for attempt in range(self.config.max_api_retries):
            try:
                response = self._openai.embeddings.create(input=[text], model=self.config.embedding_model)
                return response.data[0].embedding
            except Exception as exc:
                last_exc = exc
                if attempt == self.config.max_api_retries - 1 or not is_transient_api_error(exc):
                    break
                time.sleep(self.config.initial_backoff_seconds * (2 ** attempt))
        raise RuntimeError(str(last_exc or "embedding_request_failed"))

    def _structured_retrieve(
        self,
        class_id: int,
        section_types: list[str] | None = None,
    ) -> list[RetrievedChunk]:
        requested_sections = section_types or SECTION_TYPES
        where_filter: dict[str, Any] = {
            "$and": [
                {"class_id": class_id},
                {"section_type": {"$in": requested_sections}},
            ]
        }
        results = self._collection.get(
            where=where_filter,
            limit=max(self.config.top_k_structured, len(requested_sections)),
            include=["documents", "metadatas"],
        )

        chunks: list[RetrievedChunk] = []
        if results and results["ids"]:
            for i, chunk_id in enumerate(results["ids"]):
                meta = results["metadatas"][i] if results["metadatas"] else {}
                doc = results["documents"][i] if results["documents"] else ""
                section = meta.get("section_type", "")
                chunks.append(
                    RetrievedChunk(
                        chunk_id=chunk_id,
                        source="RAG1_KB_v2.0",
                        section=section,
                        relevance_score=self.SECTION_PRIORITY.get(section, 0.5),
                        content=doc,
                        icd10=meta.get("icd10", ""),
                        references=[],
                    )
                )

        chunks.sort(key=lambda chunk: self.SECTION_PRIORITY.get(chunk.section, 0.0), reverse=True)
        return chunks

    def _semantic_retrieve(
        self,
        query: str,
        top_k: int = 10,
    ) -> list[RetrievedChunk]:
        if self.config.safe_mode:
            print("[Retriever] SAFE_MODE active, semantic retrieval skipped.")
            return []

        cache_key = stable_hash("semantic", self.config.embedding_model, query, top_k)
        if self.config.enable_response_cache:
            cached = self._cache.get("semantic", cache_key)
            if isinstance(cached, list):
                return [RetrievedChunk(**item) for item in cached]

        try:
            query_embedding = self._embed_query(query)
            results = self._collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            print(f"[Retriever] Semantic retrieval unavailable, falling back to structured-only: {exc}")
            return []

        chunks: list[RetrievedChunk] = []
        if results and results["ids"] and results["ids"][0]:
            for i, chunk_id in enumerate(results["ids"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                doc = results["documents"][0][i] if results["documents"] else ""
                distance = results["distances"][0][i] if results["distances"] else 1.0
                similarity = max(0.0, 1.0 - distance)
                chunks.append(
                    RetrievedChunk(
                        chunk_id=chunk_id,
                        source="RAG1_KB_v2.0",
                        section=meta.get("section_type", ""),
                        relevance_score=round(similarity, 4),
                        content=doc,
                        icd10=meta.get("icd10", ""),
                        references=[],
                    )
                )
        if self.config.enable_response_cache:
            self._cache.set("semantic", cache_key, [chunk.model_dump(mode="json") for chunk in chunks])
        return chunks

    def retrieve(
        self,
        class_id: int,
        class_name: str,
        laterality: str = "N/A",
        severity_hint: str = "unknown",
        section_types: list[str] | None = None,
        top_k: int | None = None,
    ) -> list[RetrievedChunk]:
        structured_chunks = self._structured_retrieve(class_id=class_id, section_types=section_types)

        query_parts = [
            f"Chest X-ray findings and differential diagnosis for {class_name}",
            "severity assessment criteria and clinical significance",
        ]
        if laterality != "N/A":
            query_parts.append(f"laterality: {laterality}")
        if severity_hint != "unknown":
            query_parts.append(f"severity: {severity_hint}")

        semantic_limit = min(top_k or self.config.top_k_semantic, self.config.top_k_semantic)
        semantic_chunks = self._semantic_retrieve(query=", ".join(query_parts), top_k=semantic_limit + 4)

        structured_ids = {chunk.chunk_id for chunk in structured_chunks}
        semantic_extras: list[RetrievedChunk] = []
        for chunk in sorted(semantic_chunks, key=lambda item: item.relevance_score, reverse=True):
            if chunk.chunk_id in structured_ids:
                continue
            semantic_extras.append(chunk)
            if len(semantic_extras) >= semantic_limit:
                break

        return structured_chunks + semantic_extras
