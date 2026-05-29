"""Resume an interrupted Pinecone index build from a verse offset, with strict
HTTP timeouts so a hung connection can't stall the run again.

Usage:  python scripts/resume_index.py [START_OFFSET]    (default: 0)

Idempotent — upserts are keyed by verse ref, so re-running an already-indexed
slice is harmless.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from dotenv import load_dotenv

load_dotenv()

from openai import OpenAI  # noqa: E402

from app.config import config  # noqa: E402
from app.retrieval import bible_index  # noqa: E402
from app.scripture import all_verses  # noqa: E402

EMBED_BATCH = 200
UPSERT_BATCH = 100

# Strict timeouts: 30s per request, 10s to connect. If a call hangs, fail fast
# and let the retry loop below try again instead of blocking for 10 minutes.
_client = OpenAI(
    api_key=config.openrouter_api_key,
    base_url=config.openrouter_base_url,
    default_headers={
        "HTTP-Referer": config.openrouter_referer,
        "X-Title": config.openrouter_title,
    },
    timeout=httpx.Timeout(30.0, connect=10.0),
    max_retries=2,
)


def embed_with_timeout(texts: list[str]) -> list[list[float]]:
    res = _client.embeddings.create(model=config.embed_model, input=texts)
    return [d.embedding for d in sorted(res.data, key=lambda d: d.index)]


def main() -> None:
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    verses = all_verses()
    todo = verses[start:]
    print(f"Resuming at offset {start}: {len(todo)}/{len(verses)} verses to upsert.")

    index = bible_index()
    upserted = 0
    for i in range(0, len(todo), EMBED_BATCH):
        batch = todo[i : i + EMBED_BATCH]
        vectors = embed_with_timeout([v.text for v in batch])
        records = [
            {
                "id": v.ref,
                "values": vectors[j],
                "metadata": {
                    "ref": v.ref, "book": v.book, "chapter": v.chapter,
                    "verse": v.verse, "text": v.text,
                },
            }
            for j, v in enumerate(batch)
        ]
        for k in range(0, len(records), UPSERT_BATCH):
            index.upsert(vectors=records[k : k + UPSERT_BATCH])
        upserted += len(batch)
        print(f"  Upserted {start + upserted}/{len(verses)}", flush=True)

    print(f"\nDone. {start + upserted} verses now in '{config.pinecone_index}'.")


if __name__ == "__main__":
    main()
