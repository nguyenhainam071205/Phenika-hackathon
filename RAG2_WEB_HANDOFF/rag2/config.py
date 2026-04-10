"""
Centralized configuration for RAG2.

Mirrors rag1/config.py structure but with RAG2-specific settings.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_REPO_ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass(frozen=True)
class RAG2Config:
    """Immutable configuration for RAG2 pipeline."""

    # ── GitHub Models API ─────────────────────────────────────
    github_token: str = field(default_factory=lambda: _env("GITHUB_TOKEN"))
    api_base_url: str = "https://models.github.ai/inference"

    # LLM for report generation
    llm_model: str = "openai/gpt-4o-mini"

    # Embedding model (same as RAG1 for consistency)
    embedding_model: str = "openai/text-embedding-3-small"
    embedding_dim: int = 1536

    # ── Paths ─────────────────────────────────────────────────
    repo_root: Path = field(default_factory=lambda: _REPO_ROOT)

    @property
    def kb_data_dir(self) -> Path:
        return self.repo_root / "rag2" / "kb_data"

    @property
    def chroma_persist_dir(self) -> Path:
        return self.repo_root / "rag2" / "chroma_store"

    # ── Retrieval ─────────────────────────────────────────────
    # Multi-query parallel: 3 queries, top_k per query
    top_k_per_query: int = 5
    # After re-ranking, keep top N chunks for prompt
    top_k_final: int = 3

    # Re-ranking weights (spec Section 4.3)
    weight_cosine: float = 0.5
    weight_pathology_match: float = 0.3
    weight_severity_match: float = 0.2

    # ── Generation ────────────────────────────────────────────
    temperature: float = 0.15  # Lower than RAG1 for more deterministic reports
    max_tokens: int = 4096  # Reports are longer than individual findings

    # ── Output ────────────────────────────────────────────────
    default_language: str = "vi+en"  # vi | en | vi+en
    default_report_standard: str = "BYT"  # BYT | ACR | BYT_ACR

    def validate(self) -> None:
        """Raise if critical settings are missing."""
        if not self.github_token:
            raise ValueError(
                "GITHUB_TOKEN is not set. "
                "Add it to .env or export GITHUB_TOKEN=ghp_..."
            )
