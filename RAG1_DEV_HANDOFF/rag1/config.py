"""
Centralized configuration for RAG1.

All settings are read from environment variables or sensible defaults.
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
class RAG1Config:
    """Immutable configuration for RAG1 pipeline."""

    # ── GitHub Models API ─────────────────────────────────────
    github_token: str = field(default_factory=lambda: _env("GITHUB_TOKEN"))
    api_base_url: str = "https://models.github.ai/inference"

    # LLM for generation
    llm_model: str = "openai/gpt-4o-mini"

    # Embedding model
    embedding_model: str = "openai/text-embedding-3-small"
    embedding_dim: int = 1536

    # ── Paths ─────────────────────────────────────────────────
    repo_root: Path = field(default_factory=lambda: _REPO_ROOT)

    @property
    def kb_pdf_path(self) -> Path:
        return self.repo_root / "dataRAG1" / "RAG1_Knowledge_Base_CXR14_v2.pdf"

    @property
    def chroma_persist_dir(self) -> Path:
        return self.repo_root / "rag1" / "chroma_store"

    @property
    def yolo_weights_path(self) -> Path:
        return self.repo_root / "Results" / "v3" / "weights" / "best.pt"

    # ── Retrieval ─────────────────────────────────────────────
    top_k_structured: int = 5
    top_k_semantic: int = 5
    top_k_final: int = 5

    # ── Generation ────────────────────────────────────────────
    temperature: float = 0.2
    max_tokens: int = 2048

    # ── Output ────────────────────────────────────────────────
    default_language: str = "vi"  # vi | en | bilingual

    def validate(self) -> None:
        """Raise if critical settings are missing."""
        if not self.github_token:
            raise ValueError(
                "GITHUB_TOKEN is not set. "
                "Add it to .env or export GITHUB_TOKEN=ghp_..."
            )
        if not self.kb_pdf_path.exists():
            raise FileNotFoundError(
                f"Knowledge base PDF not found: {self.kb_pdf_path}"
            )
