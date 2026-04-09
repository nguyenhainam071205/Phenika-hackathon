"""
Hybrid Retriever — Structured lookup + Semantic search + RRF reranking.

Two-stage retrieval:
1. Structured: Filter chunks by class_id → guaranteed relevant sections
2. Semantic: ChromaDB cosine search → additional context from related classes
3. RRF: Merge and rerank results
"""

from __future__ import annotations

from typing import Any

import chromadb
from openai import OpenAI

from rag1.config import RAG1Config
from rag1.kb_schema import RetrievedChunk


class HybridRetriever:
    """
    Hybrid retrieval combining structured class filtering with semantic search.
    """

    def __init__(self, config: RAG1Config) -> None:
        self.config = config
        self._chroma_client = chromadb.PersistentClient(
            path=str(config.chroma_persist_dir)
        )
        self._collection = self._chroma_client.get_collection("rag1_kb")
        self._openai = OpenAI(
            base_url=config.api_base_url,
            api_key=config.github_token,
        )

    def _embed_query(self, text: str) -> list[float]:
        """Embed a single query string."""
        response = self._openai.embeddings.create(
            input=[text],
            model=self.config.embedding_model,
        )
        return response.data[0].embedding

    def _structured_retrieve(
        self,
        class_id: int,
        section_types: list[str] | None = None,
        top_k: int = 10,
    ) -> list[RetrievedChunk]:
        """
        Retrieve chunks filtered by class_id (and optionally section_type).
        This guarantees we get the right class knowledge.
        """
        where_filter: dict[str, Any] = {"class_id": class_id}
        if section_types:
            where_filter = {
                "$and": [
                    {"class_id": class_id},
                    {"section_type": {"$in": section_types}},
                ]
            }

        results = self._collection.get(
            where=where_filter,
            limit=top_k,
            include=["documents", "metadatas"],
        )

        chunks: list[RetrievedChunk] = []
        if results and results["ids"]:
            for i, chunk_id in enumerate(results["ids"]):
                meta = results["metadatas"][i] if results["metadatas"] else {}
                doc = results["documents"][i] if results["documents"] else ""
                chunks.append(
                    RetrievedChunk(
                        chunk_id=chunk_id,
                        source="RAG1_KB_v2.0",
                        section=meta.get("section_type", ""),
                        relevance_score=1.0,  # Exact match = max score
                        content=doc,
                        icd10=meta.get("icd10", ""),
                        references=[],
                    )
                )
        return chunks

    def _semantic_retrieve(
        self,
        query: str,
        top_k: int = 10,
        exclude_class_id: int | None = None,
    ) -> list[RetrievedChunk]:
        """
        Semantic similarity search via ChromaDB.
        Optionally exclude a class_id (to find cross-class context).
        """
        query_embedding = self._embed_query(query)

        where_filter = None
        if exclude_class_id is not None:
            where_filter = {"class_id": {"$ne": exclude_class_id}}

        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )

        chunks: list[RetrievedChunk] = []
        if results and results["ids"] and results["ids"][0]:
            for i, chunk_id in enumerate(results["ids"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                doc = results["documents"][0][i] if results["documents"] else ""
                distance = results["distances"][0][i] if results["distances"] else 1.0

                # ChromaDB cosine distance → similarity score
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
        return chunks

    @staticmethod
    def _rrf_merge(
        structured: list[RetrievedChunk],
        semantic: list[RetrievedChunk],
        top_k: int = 5,
        k: int = 60,
    ) -> list[RetrievedChunk]:
        """
        Reciprocal Rank Fusion to merge two ranked lists.

        RRF score = Σ 1 / (k + rank_i) for each list.
        """
        scores: dict[str, float] = {}
        chunk_map: dict[str, RetrievedChunk] = {}

        for rank, chunk in enumerate(structured):
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (k + rank)
            chunk_map[chunk.chunk_id] = chunk

        for rank, chunk in enumerate(semantic):
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (k + rank)
            if chunk.chunk_id not in chunk_map:
                chunk_map[chunk.chunk_id] = chunk

        # Sort by RRF score descending
        sorted_ids = sorted(scores.keys(), key=lambda cid: scores[cid], reverse=True)

        merged: list[RetrievedChunk] = []
        for cid in sorted_ids[:top_k]:
            chunk = chunk_map[cid]
            # Update relevance_score with RRF score
            chunk.relevance_score = round(scores[cid], 4)
            merged.append(chunk)

        return merged

    def retrieve(
        self,
        class_id: int,
        class_name: str,
        laterality: str = "N/A",
        severity_hint: str = "unknown",
        section_types: list[str] | None = None,
        top_k: int | None = None,
    ) -> list[RetrievedChunk]:
        """
        Hybrid retrieval for a single detection.

        1. Structured: Get all sections for the detected class
        2. Semantic: Search for related context (DDx from other classes, etc.)
        3. RRF merge both results
        """
        final_k = top_k or self.config.top_k_final

        # Stage 1: Structured (exact class match)
        structured_chunks = self._structured_retrieve(
            class_id=class_id,
            section_types=section_types,
            top_k=self.config.top_k_structured,
        )

        # Stage 2: Semantic (broader context)
        query_parts = [f"X-ray findings for {class_name}"]
        if laterality != "N/A":
            query_parts.append(f"laterality: {laterality}")
        if severity_hint != "unknown":
            query_parts.append(f"severity: {severity_hint}")
        semantic_query = ", ".join(query_parts)

        semantic_chunks = self._semantic_retrieve(
            query=semantic_query,
            top_k=self.config.top_k_semantic,
        )

        # Stage 3: RRF merge
        merged = self._rrf_merge(structured_chunks, semantic_chunks, top_k=final_k)

        return merged
