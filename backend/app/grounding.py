"""Grounding: the anti-hallucination core.

Two halves:
  - build_grounding (input side): assemble a CONTEXT block of ONLY canonical
    verses — topical retrieval + resolution of any references the user typed
    (confirming real ones, flagging fabricated/non-existent ones).
  - verify_citations (output side): re-check every reference the model emitted
    against the canonical KJV; unverifiable ones are flagged before display.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.retrieval import RetrievedVerse, semantic_search
from app.scripture import (
    Verse,
    extract_references,
    get_verse,
    reference_exists,
    resolve_verses,
)

# ─────────────────────────── Output side: verify ───────────────────────────


@dataclass
class CitationCheck:
    raw: str
    ref: str | None
    status: str  # "verified" | "invalid_book" | "not_found"
    text: str | None = None


@dataclass
class VerificationResult:
    citations: list[CitationCheck] = field(default_factory=list)

    @property
    def verified(self) -> list[CitationCheck]:
        return [c for c in self.citations if c.status == "verified"]

    @property
    def unverified(self) -> list[CitationCheck]:
        return [c for c in self.citations if c.status != "verified"]

    @property
    def has_unverified(self) -> bool:
        return len(self.unverified) > 0


def verify_citations(answer: str) -> VerificationResult:
    seen: set[str] = set()
    citations: list[CitationCheck] = []

    for raw, parsed in extract_references(answer):
        if parsed is None:
            key = f"invalid:{raw.lower()}"
            if key in seen:
                continue
            seen.add(key)
            citations.append(CitationCheck(raw=raw, ref=None, status="invalid_book"))
            continue

        canonical_ref = f"{parsed.book} {parsed.chapter}"
        if parsed.start_verse is not None:
            canonical_ref += f":{parsed.start_verse}"
            if parsed.end_verse:
                canonical_ref += f"-{parsed.end_verse}"
        if canonical_ref in seen:
            continue
        seen.add(canonical_ref)

        if not reference_exists(parsed):
            citations.append(CitationCheck(raw, canonical_ref, "not_found"))
            continue
        verse = (
            get_verse(parsed.book, parsed.chapter, parsed.start_verse)
            if parsed.start_verse is not None
            else None
        )
        citations.append(
            CitationCheck(raw, canonical_ref, "verified", verse.text if verse else None)
        )

    return VerificationResult(citations=citations)


# ─────────────────────────── Input side: build context ───────────────────────────


@dataclass
class UserReference:
    raw: str
    status: str  # "verified" | "invalid_book" | "not_found"
    canonical_ref: str | None = None
    verses: list[Verse] = field(default_factory=list)


@dataclass
class Grounding:
    retrieved: list[RetrievedVerse] = field(default_factory=list)
    user_references: list[UserReference] = field(default_factory=list)
    has_fabricated_user_ref: bool = False
    context_block: str = ""


def build_grounding(user_message: str, *, skip_semantic: bool = False) -> Grounding:
    # 1. Topical semantic retrieval (best-effort; never fail the turn on this).
    #    Skipped on the refusal path, where we only resolve explicit references.
    retrieved: list[RetrievedVerse] = []
    if not skip_semantic:
        try:
            retrieved = semantic_search(user_message)
        except Exception as e:  # noqa: BLE001
            print(f"semantic_search failed: {e}")

    # 2. Resolve references the user typed.
    user_references: list[UserReference] = []
    for raw, parsed in extract_references(user_message):
        if parsed is None:
            user_references.append(UserReference(raw, "invalid_book"))
            continue
        canonical_ref = f"{parsed.book} {parsed.chapter}"
        if parsed.start_verse is not None:
            canonical_ref += f":{parsed.start_verse}"
            if parsed.end_verse:
                canonical_ref += f"-{parsed.end_verse}"
        if not reference_exists(parsed):
            user_references.append(UserReference(raw, "not_found", canonical_ref))
            continue
        user_references.append(
            UserReference(raw, "verified", canonical_ref, resolve_verses(parsed))
        )

    return Grounding(
        retrieved=retrieved,
        user_references=user_references,
        has_fabricated_user_ref=any(r.status != "verified" for r in user_references),
        context_block=_format_context(retrieved, user_references),
    )


def _format_context(
    retrieved: list[RetrievedVerse], user_references: list[UserReference]
) -> str:
    parts = ["=== CANONICAL SCRIPTURE CONTEXT (KJV) ==="]

    if retrieved:
        parts.append("\n[Verses retrieved by topical relevance]")
        parts += [f'- {r.verse.ref} — "{r.verse.text}"' for r in retrieved]
    else:
        parts.append("\n[No verses retrieved by topical search.]")

    if user_references:
        parts.append("\n[References the user mentioned — verification result]")
        for r in user_references:
            if r.status == "verified":
                text = " ".join(f'{v.ref} "{v.text}"' for v in r.verses)
                parts.append(f'- "{r.raw}" → VERIFIED ({r.canonical_ref}): {text}')
            elif r.status == "not_found":
                parts.append(
                    f'- "{r.raw}" → NOT FOUND: that reference ({r.canonical_ref}) does not '
                    "exist in the canon. Treat as a fabricated/incorrect citation."
                )
            else:
                parts.append(
                    f'- "{r.raw}" → INVALID: not a real book of the Bible. '
                    "Treat as a fabricated citation."
                )

    return "\n".join(parts)
