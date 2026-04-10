from __future__ import annotations

import sys
import time
from pathlib import Path

from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag2.config import RAG2Config


def main() -> None:
    config = RAG2Config()
    config.validate()

    client = OpenAI(
        base_url=config.api_base_url,
        api_key=config.github_token,
    )
    query = "mau bao cao xquang tran dich mang phoi phai muc do vua"

    print(
        f"[Embedding Test] start model={config.embedding_model} "
        f"base_url={config.api_base_url}"
    )
    started_at = time.perf_counter()
    try:
        response = client.embeddings.create(
            input=[query],
            model=config.embedding_model,
        )
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        print(
            f"[Embedding Test] failed after {elapsed_ms}ms: "
            f"{type(exc).__name__}: {exc}"
        )
        raise

    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    embedding = response.data[0].embedding
    print(
        f"[Embedding Test] success in {elapsed_ms}ms "
        f"dimensions={len(embedding)}"
    )


if __name__ == "__main__":
    main()
