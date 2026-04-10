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

    print(
        f"[Chat Test] start model={config.llm_model} "
        f"base_url={config.api_base_url}"
    )
    started_at = time.perf_counter()
    try:
        response = client.chat.completions.create(
            model=config.llm_model,
            messages=[
                {
                    "role": "system",
                    "content": "Return compact JSON only.",
                },
                {
                    "role": "user",
                    "content": (
                        'Return {"status":"ok","task":"chat_test"} and nothing else.'
                    ),
                },
            ],
            temperature=0.0,
            max_tokens=128,
        )
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        print(
            f"[Chat Test] failed after {elapsed_ms}ms: "
            f"{type(exc).__name__}: {exc}"
        )
        raise

    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    content = response.choices[0].message.content or ""
    print(f"[Chat Test] success in {elapsed_ms}ms")
    print(content)


if __name__ == "__main__":
    main()
