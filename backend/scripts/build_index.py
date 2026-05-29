"""Embed every KJV verse and upsert into Pinecone. Idempotent — re-running
overwrites by ref-keyed ID. Creates the serverless index if it doesn't exist.

Run from the backend dir:  python scripts/build_index.py
(after `python scripts/prepare_bible.py`, with .env filled in)
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from pinecone import ServerlessSpec  # noqa: E402

from app.config import config  # noqa: E402
from app.llm import embed  # noqa: E402
from app.scripture import all_verses  # noqa: E402
from app.retrieval import bible_index, pinecone  # noqa: E402

EMBED_BATCH = 200
UPSERT_BATCH = 100


def ensure_index() -> None:
    pc = pinecone()
    if pc.has_index(config.pinecone_index):
        print(f'Index "{config.pinecone_index}" exists.')
        return
    print(
        f'Creating serverless index "{config.pinecone_index}" '
        f"(dim={config.embed_dim}, cosine)..."
    )
    # create_index blocks until the index is ready (timeout=None default).
    pc.create_index(
        name=config.pinecone_index,
        dimension=config.embed_dim,
        metric="cosine",
        spec=ServerlessSpec(cloud="aws", region="us-east-1"),
    )
    print("Index ready.")


def main() -> None:
    verses = all_verses()
    print(f"Loaded {len(verses)} verses.")

    ensure_index()
    index = bible_index()

    upserted = 0
    for i in range(0, len(verses), EMBED_BATCH):
        batch = verses[i : i + EMBED_BATCH]
        vectors = embed([v.text for v in batch])
        records = [
            {
                "id": v.ref,
                "values": vectors[j],
                "metadata": {
                    "ref": v.ref,
                    "book": v.book,
                    "chapter": v.chapter,
                    "verse": v.verse,
                    "text": v.text,
                },
            }
            for j, v in enumerate(batch)
        ]
        for k in range(0, len(records), UPSERT_BATCH):
            index.upsert(vectors=records[k : k + UPSERT_BATCH])
        upserted += len(batch)
        print(f"\rUpserted {upserted}/{len(verses)}", end="", flush=True)

    print(f'\nDone. Indexed {upserted} verses into "{config.pinecone_index}".')


if __name__ == "__main__":
    main()
