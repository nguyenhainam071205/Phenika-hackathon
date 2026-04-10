"""
RAG2 Retriever — Multi-query parallel retrieval with pathology-aware re-ranking.

Implements spec Section 4:
  - 3 parallel queries (pattern, severity, clinical context)
  - Re-ranking: 0.5×cosine + 0.3×pathology_match + 0.2×severity_match
  - Returns top 3 chunks
"""

from __future__ import annotations

import chromadb
from openai import OpenAI

from rag2.config import RAG2Config
from rag2.schema import DoctorRevisedJSON


class RAG2Retriever:
    """Multi-query retriever with pathology-aware re-ranking."""

    def __init__(self, config: RAG2Config) -> None:
        self.config = config
        self._chroma_client = chromadb.PersistentClient(
            path=str(config.chroma_persist_dir)
        )
        self._collection = self._chroma_client.get_collection("rag2_kb")
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

    def _build_queries(self, revised: DoctorRevisedJSON) -> list[str]:
        """
        Build 3 parallel queries from Doctor-Revised JSON.

        Q1: Pattern matching — tìm mẫu báo cáo theo tổ hợp bệnh lý
        Q2: Severity + combination — tìm mẫu cùng mức độ
        Q3: Clinical context — tìm few-shot tương tự hồ sơ bệnh nhân
        """
        findings = revised.confirmed_findings
        patient = revised.patient_context

        if not findings:
            return ["mau bao cao xquang binh thuong khong ton thuong"]

        class_names = [f.class_name for f in findings]
        severities = list(set(f.severity for f in findings))
        lateralities = list(set(
            f.laterality for f in findings if f.laterality != "N/A"
        ))

        # Q1: Pattern matching
        q1 = f"mau bao cao xquang {' '.join(class_names)} {' '.join(lateralities)}"

        # Q2: Severity + BYT combination
        q2 = f"bao cao chan doan hinh anh {' '.join(class_names)} {' '.join(severities)} BYT"

        # Q3: Clinical context
        age = patient.age or 0
        age_group = "nguoi cao tuoi" if age >= 60 else "nguoi lon"
        sex_str = "nam" if patient.sex == "M" else "nu"
        primary = class_names[0] if class_names else ""
        q3 = f"vi du bao cao {age_group} {sex_str} {primary}"

        return [q1, q2, q3]

    def _semantic_search(
        self,
        query: str,
        top_k: int = 5,
    ) -> list[dict]:
        """Run a single semantic search query against ChromaDB."""
        query_embedding = self._embed_query(query)

        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )

        chunks = []
        if results and results["ids"] and results["ids"][0]:
            for i, chunk_id in enumerate(results["ids"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                doc = results["documents"][0][i] if results["documents"] else ""
                distance = results["distances"][0][i] if results["distances"] else 1.0

                # ChromaDB cosine distance → similarity score
                similarity = max(0.0, 1.0 - distance)

                chunks.append({
                    "chunk_id": chunk_id,
                    "content": doc,
                    "cosine_score": similarity,
                    "layer": meta.get("layer", ""),
                    "pathology_group": meta.get("pathology_group", ""),
                    "class_names": meta.get("class_names", ""),
                    "chunk_type": meta.get("chunk_type", ""),
                    "source_file": meta.get("source_file", ""),
                })

        return chunks

    def _rerank(
        self,
        chunks: list[dict],
        target_class_names: set[str],
        target_severities: set[str],
    ) -> list[dict]:
        """
        Re-rank chunks using weighted scoring (spec Section 4.3).

        Score_final = 0.5 × cosine + 0.3 × pathology_match + 0.2 × severity_match
        """
        w_cos = self.config.weight_cosine
        w_path = self.config.weight_pathology_match
        w_sev = self.config.weight_severity_match

        for chunk in chunks:
            cosine = chunk["cosine_score"]

            # Pathology match: +1.0 if any class_name matches
            chunk_classes = set(chunk.get("class_names", "").split("|"))
            pathology_bonus = 1.0 if target_class_names & chunk_classes else 0.0

            # Severity match: check if severity keyword appears in content
            content_lower = chunk.get("content", "").lower()
            severity_bonus = 0.0
            for sev in target_severities:
                if sev.lower() in content_lower:
                    severity_bonus = 0.5
                    break

            chunk["final_score"] = (
                w_cos * cosine
                + w_path * pathology_bonus
                + w_sev * severity_bonus
            )

        # Sort by final score descending
        chunks.sort(key=lambda c: c["final_score"], reverse=True)
        return chunks

    def retrieve(self, revised: DoctorRevisedJSON) -> list[dict]:
        """
        Full retrieval pipeline:
          1. Build 3 parallel queries
          2. Run semantic search for each
          3. Merge and deduplicate
          4. Re-rank with pathology + severity bonuses
          5. Return top K chunks

        Returns:
            List of chunk dicts with keys: chunk_id, content, layer,
            pathology_group, final_score, etc.
        """
        queries = self._build_queries(revised)
        top_k_per = self.config.top_k_per_query
        final_k = self.config.top_k_final

        # Collect target metadata for re-ranking
        target_classes = set(f.class_name for f in revised.confirmed_findings)
        target_severities = set(f.severity for f in revised.confirmed_findings)

        # Run parallel queries and merge
        seen_ids: set[str] = set()
        all_chunks: list[dict] = []

        for i, query in enumerate(queries):
            print(f"    [Q{i+1}] {query[:80]}...")
            results = self._semantic_search(query, top_k=top_k_per)
            for chunk in results:
                if chunk["chunk_id"] not in seen_ids:
                    seen_ids.add(chunk["chunk_id"])
                    chunk["query_source"] = f"Q{i+1}"
                    all_chunks.append(chunk)

        print(f"    [Merge] {len(all_chunks)} unique chunks from {len(queries)} queries")

        # Re-rank
        ranked = self._rerank(all_chunks, target_classes, target_severities)

        # Return top K
        top_chunks = ranked[:final_k]
        for c in top_chunks:
            print(f"    [Top] {c['chunk_id']} layer={c['layer']} "
                  f"score={c['final_score']:.3f} group={c['pathology_group']}")

        return top_chunks
