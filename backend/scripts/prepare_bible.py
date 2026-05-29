"""One-time data prep: convert the raw single-file KJV dataset
(data/bible/kjv_raw.json) into a clean, flat verse list (data/bible/kjv.json)
that is the app's source of truth for exact lookup + citation verification.

The raw KJV embeds two kinds of brace annotations:
  {was}                    -> translator-supplied italic words (KEEP content)
  {the light...: Heb. ...} -> marginal/translation notes      (DROP entirely)
We distinguish them by the presence of a colon inside the braces.

Run from the backend dir:  python scripts/prepare_bible.py
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.scripture import BOOK_NAMES  # noqa: E402

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RAW = os.path.join(_HERE, "data", "bible", "kjv_raw.json")
_OUT = os.path.join(_HERE, "data", "bible", "kjv.json")


def clean_verse_text(raw: str) -> str:
    raw = re.sub(r"\{[^{}]*:[^{}]*\}", " ", raw)  # drop marginal notes
    raw = re.sub(r"[{}]", "", raw)  # keep supplied words, drop braces
    raw = re.sub(r"\[[^\][]*:[^\][]*\]", " ", raw)  # drop bracketed notes
    raw = re.sub(r"\s+([,.;:!?])", r"\1", raw)
    raw = re.sub(r"\s+", " ", raw)
    return raw.strip()


def main() -> None:
    with open(_RAW, encoding="utf-8-sig") as f:  # utf-8-sig strips BOM
        books = json.load(f)

    if len(books) != len(BOOK_NAMES):
        raise SystemExit(
            f"Expected {len(BOOK_NAMES)} books, got {len(books)}. Dataset order mismatch."
        )

    verses = []
    for book_idx, raw_book in enumerate(books):
        name = BOOK_NAMES[book_idx]
        for ch_idx, chapter_verses in enumerate(raw_book["chapters"]):
            chapter = ch_idx + 1
            for v_idx, text in enumerate(chapter_verses):
                verse = v_idx + 1
                clean = clean_verse_text(text)
                if not clean:
                    continue
                verses.append(
                    {
                        "ref": f"{name} {chapter}:{verse}",
                        "book": name,
                        "chapter": chapter,
                        "verse": verse,
                        "text": clean,
                    }
                )

    with open(_OUT, "w", encoding="utf-8") as f:
        json.dump(verses, f, ensure_ascii=False)

    print(f"Wrote {len(verses)} verses to data/bible/kjv.json")
    j316 = next((v for v in verses if v["ref"] == "John 3:16"), None)
    print("Sample — John 3:16:", j316["text"] if j316 else "(missing)")


if __name__ == "__main__":
    main()
