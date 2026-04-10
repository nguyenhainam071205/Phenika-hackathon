"""
Runtime helpers for caching and resilient API behavior in RAG1.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def stable_hash(*parts: Any) -> str:
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_sha256(path: str) -> str:
    target = Path(path)
    if not target.exists() or not target.is_file():
        return ""
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_rate_limit_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(
        token in text
        for token in (
            "rate limit",
            "ratelimit",
            "too many requests",
            "status code: 429",
            "status code 429",
            "quota",
        )
    )


def is_transient_api_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return is_rate_limit_error(exc) or any(
        token in text
        for token in (
            "timeout",
            "timed out",
            "connection reset",
            "connection aborted",
            "temporary failure",
            "bad gateway",
            "gateway timeout",
            "service unavailable",
            "internal server error",
            "502",
            "503",
            "504",
        )
    )


class JsonDiskCache:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _target(self, namespace: str, key: str) -> Path:
        return self.root / namespace / f"{key}.json"

    def get(self, namespace: str, key: str) -> Any | None:
        path = self._target(namespace, key)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def set(self, namespace: str, key: str, value: Any) -> None:
        path = self._target(namespace, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
