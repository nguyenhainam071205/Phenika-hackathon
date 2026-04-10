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
    llm_model: str = field(default_factory=lambda: _env("RAG1_LLM_MODEL", "openai/gpt-4o-mini"))
    vision_model: str = field(default_factory=lambda: _env("RAG1_VISION_MODEL", "openai/gpt-4o-mini"))

    # Embedding model
    embedding_model: str = "openai/text-embedding-3-small"
    embedding_dim: int = 1536
    safe_mode: bool = field(default_factory=lambda: _env("RAG1_SAFE_MODE", "true").lower() in {"1", "true", "yes"})

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

    @property
    def cache_dir(self) -> Path:
        return self.repo_root / "outputs" / "cache" / "rag1"

    # ── Retrieval ─────────────────────────────────────────────
    top_k_structured: int = 8
    top_k_semantic: int = 5
    top_k_final: int = 7

    # ── Generation ────────────────────────────────────────────
    temperature: float = 0.2
    max_tokens: int = 2048
    enable_response_cache: bool = field(
        default_factory=lambda: _env("RAG1_ENABLE_RESPONSE_CACHE", "true").lower() in {"1", "true", "yes"}
    )
    max_api_retries: int = field(default_factory=lambda: int(_env("RAG1_MAX_API_RETRIES", "3") or "3"))
    initial_backoff_seconds: float = field(
        default_factory=lambda: float(_env("RAG1_INITIAL_BACKOFF_SECONDS", "1.0") or "1.0")
    )
    enable_vision_verification: bool = field(
        default_factory=lambda: _env("RAG1_ENABLE_VISION_VERIFICATION", "false").lower() in {"1", "true", "yes"}
    )
    vision_only_on_review_cases: bool = field(
        default_factory=lambda: _env("RAG1_VISION_ONLY_ON_REVIEW_CASES", "true").lower() in {"1", "true", "yes"}
    )
    vision_confidence_threshold: float = field(
        default_factory=lambda: float(_env("RAG1_VISION_CONFIDENCE_THRESHOLD", "0.65") or "0.65")
    )
    vision_max_attempts_per_image: int = field(
        default_factory=lambda: int(_env("RAG1_VISION_MAX_ATTEMPTS_PER_IMAGE", "1") or "1")
    )

    # ── Output ────────────────────────────────────────────────
    default_language: str = "vi"  # vi | en | bilingual

    def validate(self) -> None:
        """Raise if critical settings are missing."""
        if not self.safe_mode and not self.github_token:
            raise ValueError(
                "GITHUB_TOKEN is not set while RAG1_SAFE_MODE=false. "
                "Add it to .env or export GITHUB_TOKEN=ghp_..."
            )
        if not self.kb_pdf_path.exists():
            raise FileNotFoundError(
                f"Knowledge base PDF not found: {self.kb_pdf_path}"
            )
