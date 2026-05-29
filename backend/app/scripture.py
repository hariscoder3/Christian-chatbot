"""Canonical scripture: the KJV text, book registry, and reference parsing.

This module is the SOURCE OF TRUTH for exact verse lookup and citation
verification. It is fully local and deterministic — it never makes a network
call — so the anti-hallucination guarantee holds even if Pinecone/OpenRouter is
unreachable.

Contents:
  - BOOKS / resolve_book   canonical 66-book registry + alias resolution
  - Verse / get_verse ...   load + look up canonical KJV verses
  - ParsedRef / parse...    extract & validate references from free text
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

# ─────────────────────────── Book registry ───────────────────────────
# Canonical 66-book Protestant ordering. The source dataset lists books in this
# exact order, so we map by index. `aliases` lets the parser resolve "Jn"/"1 Cor";
# anything NOT here (e.g. "2 Hesitations") resolves to None — core to fake-verse
# detection.
BOOKS: list[tuple[str, str, list[str]]] = [
    ("Genesis", "OT", ["genesis", "gen", "gn", "ge"]),
    ("Exodus", "OT", ["exodus", "exo", "ex", "exod"]),
    ("Leviticus", "OT", ["leviticus", "lev", "lv"]),
    ("Numbers", "OT", ["numbers", "num", "nm", "nu"]),
    ("Deuteronomy", "OT", ["deuteronomy", "deut", "dt", "deu"]),
    ("Joshua", "OT", ["joshua", "josh", "jos", "js"]),
    ("Judges", "OT", ["judges", "judg", "jdg", "jud"]),
    ("Ruth", "OT", ["ruth", "rut", "rt", "ru"]),
    ("1 Samuel", "OT", ["1samuel", "1sam", "1sm", "1sa", "isamuel"]),
    ("2 Samuel", "OT", ["2samuel", "2sam", "2sm", "2sa", "iisamuel"]),
    ("1 Kings", "OT", ["1kings", "1kgs", "1ki", "1kin", "ikings"]),
    ("2 Kings", "OT", ["2kings", "2kgs", "2ki", "2kin", "iikings"]),
    ("1 Chronicles", "OT", ["1chronicles", "1chron", "1chr", "1ch"]),
    ("2 Chronicles", "OT", ["2chronicles", "2chron", "2chr", "2ch"]),
    ("Ezra", "OT", ["ezra", "ezr"]),
    ("Nehemiah", "OT", ["nehemiah", "neh"]),
    ("Esther", "OT", ["esther", "esth", "est"]),
    ("Job", "OT", ["job", "jb"]),
    ("Psalms", "OT", ["psalms", "psalm", "psa", "ps", "pss", "psm"]),
    ("Proverbs", "OT", ["proverbs", "prov", "prv", "pro", "pr"]),
    ("Ecclesiastes", "OT", ["ecclesiastes", "eccl", "ecc", "ec", "qoh"]),
    ("Song of Solomon", "OT", ["songofsolomon", "songofsongs", "song", "sos", "canticles"]),
    ("Isaiah", "OT", ["isaiah", "isa"]),
    ("Jeremiah", "OT", ["jeremiah", "jer", "jr"]),
    ("Lamentations", "OT", ["lamentations", "lam", "lm"]),
    ("Ezekiel", "OT", ["ezekiel", "ezek", "eze", "ezk"]),
    ("Daniel", "OT", ["daniel", "dan", "dn"]),
    ("Hosea", "OT", ["hosea", "hos"]),
    ("Joel", "OT", ["joel", "joe", "jl"]),
    ("Amos", "OT", ["amos", "amo"]),
    ("Obadiah", "OT", ["obadiah", "obad", "oba", "ob"]),
    ("Jonah", "OT", ["jonah", "jon", "jnh"]),
    ("Micah", "OT", ["micah", "mic"]),
    ("Nahum", "OT", ["nahum", "nah"]),
    ("Habakkuk", "OT", ["habakkuk", "hab", "hk"]),
    ("Zephaniah", "OT", ["zephaniah", "zeph", "zep", "zp"]),
    ("Haggai", "OT", ["haggai", "hag", "hg"]),
    ("Zechariah", "OT", ["zechariah", "zech", "zec", "zc"]),
    ("Malachi", "OT", ["malachi", "mal", "ml"]),
    ("Matthew", "NT", ["matthew", "matt", "mat", "mt"]),
    ("Mark", "NT", ["mark", "mrk", "mk"]),
    ("Luke", "NT", ["luke", "luk", "lk"]),
    ("John", "NT", ["john", "jhn", "joh", "jn"]),
    ("Acts", "NT", ["acts", "act"]),
    ("Romans", "NT", ["romans", "rom", "rm"]),
    ("1 Corinthians", "NT", ["1corinthians", "1cor", "1co", "icorinthians"]),
    ("2 Corinthians", "NT", ["2corinthians", "2cor", "2co", "iicorinthians"]),
    ("Galatians", "NT", ["galatians", "gal", "gl"]),
    ("Ephesians", "NT", ["ephesians", "eph", "ephes"]),
    ("Philippians", "NT", ["philippians", "phil", "php", "pp"]),
    ("Colossians", "NT", ["colossians", "col", "cl"]),
    ("1 Thessalonians", "NT", ["1thessalonians", "1thess", "1thes", "1th", "1ts"]),
    ("2 Thessalonians", "NT", ["2thessalonians", "2thess", "2thes", "2th", "2ts"]),
    ("1 Timothy", "NT", ["1timothy", "1tim", "1tm", "1ti"]),
    ("2 Timothy", "NT", ["2timothy", "2tim", "2tm", "2ti"]),
    ("Titus", "NT", ["titus", "tit", "tt"]),
    ("Philemon", "NT", ["philemon", "philem", "phm", "phlm"]),
    ("Hebrews", "NT", ["hebrews", "heb", "hb"]),
    ("James", "NT", ["james", "jas", "jm", "jam"]),
    ("1 Peter", "NT", ["1peter", "1pet", "1pe", "1pt", "ipeter"]),
    ("2 Peter", "NT", ["2peter", "2pet", "2pe", "2pt", "iipeter"]),
    ("1 John", "NT", ["1john", "1jhn", "1jn", "1jo", "ijohn"]),
    ("2 John", "NT", ["2john", "2jhn", "2jn", "2jo", "iijohn"]),
    ("3 John", "NT", ["3john", "3jhn", "3jn", "3jo", "iiijohn"]),
    ("Jude", "NT", ["jude", "jud", "jd"]),
    ("Revelation", "NT", ["revelation", "revelations", "rev", "rv", "apocalypse"]),
]

BOOK_NAMES: list[str] = [b[0] for b in BOOKS]

_ALIAS_MAP: dict[str, str] = {}
for _name, _t, _aliases in BOOKS:
    _ALIAS_MAP[re.sub(r"\s+", "", _name.lower())] = _name
    for _a in _aliases:
        _ALIAS_MAP[_a] = _name


def resolve_book(raw: str) -> str | None:
    """Resolve a (possibly messy) book token to a canonical name, or None."""
    return _ALIAS_MAP.get(re.sub(r"[.\s]", "", raw.lower()))


# ─────────────────────────── Verse store ───────────────────────────
_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "bible" / "kjv.json"


@dataclass(frozen=True)
class Verse:
    ref: str  # "John 3:16"
    book: str
    chapter: int
    verse: int
    text: str


_verses: list[Verse] | None = None
_by_ref: dict[str, Verse] | None = None


def _load() -> None:
    global _verses, _by_ref
    if _verses is not None:
        return
    raw = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    _verses = [
        Verse(v["ref"], v["book"], int(v["chapter"]), int(v["verse"]), v["text"])
        for v in raw
    ]
    _by_ref = {v.ref: v for v in _verses}


def all_verses() -> list[Verse]:
    _load()
    assert _verses is not None
    return _verses


def get_verse(book: str, chapter: int, verse: int) -> Verse | None:
    _load()
    assert _by_ref is not None
    return _by_ref.get(f"{book} {chapter}:{verse}")


def get_range(book: str, chapter: int, start_verse: int, end_verse: int) -> list[Verse]:
    out: list[Verse] = []
    for v in range(start_verse, end_verse + 1):
        hit = get_verse(book, chapter, v)
        if hit:
            out.append(hit)
    return out


def verse_exists(book: str, chapter: int, verse: int) -> bool:
    return get_verse(book, chapter, verse) is not None


# ─────────────────────────── Reference parsing ───────────────────────────
# book token: optional 1-3 prefix, letters, optional " of Solomon/Songs"
_REF_RE = re.compile(
    r"\b((?:[1-3]\s*)?[A-Za-z]{2,}(?:\s+of\s+[A-Za-z]+)?)\.?\s+"
    r"(\d{1,3})(?::(\d{1,3})(?:\s*[-–]\s*(\d{1,3}))?)?\b"
)


@dataclass(frozen=True)
class ParsedRef:
    raw: str
    book: str
    chapter: int
    start_verse: int | None = None  # None => whole-chapter reference
    end_verse: int | None = None


def _starts_capitalized(token: str) -> bool:
    first_alpha = next((c for c in token if c.isalpha()), "")
    return first_alpha.isupper()


def extract_references(text: str) -> list[tuple[str, ParsedRef | None]]:
    """Find scripture references. Unknown-but-reference-shaped tokens yield
    parsed=None so fabricated books are surfaced.

    Prose-safety: references are capitalized proper nouns, so a candidate must be
    capitalized — this skips matches like "the ratio is 1:2" or "meet at 1:30".
    A capitalized token that doesn't resolve to a book is only treated as a
    (fabricated) citation when it carries a chapter:verse.
    """
    out: list[tuple[str, ParsedRef | None]] = []
    for m in _REF_RE.finditer(text):
        token = m.group(1).strip()
        if not _starts_capitalized(token):
            continue
        has_verse = m.group(3) is not None
        book = resolve_book(token)
        if book is None and not has_verse:
            continue  # capitalized non-book without a verse → not a citation
        chapter = int(m.group(2))
        start_verse = int(m.group(3)) if m.group(3) else None
        end_verse = int(m.group(4)) if m.group(4) else None
        parsed = (
            ParsedRef(m.group(0).strip(), book, chapter, start_verse, end_verse)
            if book
            else None
        )
        out.append((m.group(0).strip(), parsed))
    return out


def parse_reference(text: str) -> ParsedRef | None:
    """Parse a single reference string; None if the book isn't canonical."""
    for _raw, parsed in extract_references(text):
        if parsed:
            return parsed
    return None


def reference_exists(ref: ParsedRef) -> bool:
    return verse_exists(ref.book, ref.chapter, ref.start_verse or 1)


def resolve_verses(ref: ParsedRef) -> list[Verse]:
    """Resolve a reference to its canonical verse(s). [] if it doesn't exist."""
    if ref.start_verse is None:
        return get_range(ref.book, ref.chapter, 1, 200)  # whole chapter (capped)
    if ref.end_verse and ref.end_verse > ref.start_verse:
        return get_range(ref.book, ref.chapter, ref.start_verse, ref.end_verse)
    v = get_verse(ref.book, ref.chapter, ref.start_verse)
    return [v] if v else []
