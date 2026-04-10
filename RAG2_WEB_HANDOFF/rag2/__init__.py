"""
RAG2 — Medical X-ray Report Generation (BYT Standard).

Pipeline: Doctor-Revised JSON → Knowledge retrieval → Report generation → Validation.
"""

__all__ = ["RAG2Config", "RAG2Engine"]


def __getattr__(name: str):
    if name == "RAG2Config":
        from rag2.config import RAG2Config
        return RAG2Config
    if name == "RAG2Engine":
        from rag2.engine import RAG2Engine
        return RAG2Engine
    raise AttributeError(f"module 'rag2' has no attribute {name!r}")
