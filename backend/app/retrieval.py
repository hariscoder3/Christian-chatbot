"""Vector retrieval over the KJV (Pinecone).

Embeds the query, queries Pinecone, then re-fetches each hit's text from the
LOCAL canonical Bible so grounded context always uses source-of-truth text
(Pinecone metadata is used only to identify the verse, never as its text).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from pinecone import Pinecone

from app.config import config
from app.llm import embed_one
from app.scripture import Verse, get_verse


@lru_cache(maxsize=1)
def pinecone() -> Pinecone:
    return Pinecone(api_key=config.pinecone_api_key)


def bible_index():
    return pinecone().Index(config.pinecone_index)


@dataclass(frozen=True)
class RetrievedVerse:
    verse: Verse
    score: float


def semantic_search(query: str, top_k: int | None = None) -> list[RetrievedVerse]:
    vector = embed_one(query)
    res = bible_index().query(
        vector=vector,
        top_k=top_k or config.retrieval_top_k,
        include_metadata=True,
    )
    out: list[RetrievedVerse] = []
    for match in res.matches or []:
        if (match.score or 0.0) < config.retrieval_min_score:
            continue
        md = match.metadata or {}
        book, chapter, verse = md.get("book"), md.get("chapter"), md.get("verse")
        if book is None or chapter is None or verse is None:
            continue
        canonical = get_verse(book, int(chapter), int(verse))
        if canonical is not None:
            out.append(RetrievedVerse(verse=canonical, score=match.score or 0.0))
    return out
