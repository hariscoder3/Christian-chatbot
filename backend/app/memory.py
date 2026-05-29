"""Conversation memory.

In-process per-session store with a rolling summary: recent turns are kept
verbatim for tone/topic continuity; older turns are compressed into a running
summary so context stays bounded. Demo-scale persistence (per running process).
For production this moves to SQLite/Redis keyed by user — same interface.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.llm import chat

_MAX_VERBATIM = 8  # keep last 4 exchanges verbatim
_KEEP_AFTER_SUMMARY = 4


@dataclass
class Session:
    id: str
    turns: list[dict[str, str]] = field(default_factory=list)
    summary: str = ""
    denomination_id: str = "neutral"


_store: dict[str, Session] = {}


def get_session(session_id: str) -> Session:
    s = _store.get(session_id)
    if s is None:
        s = Session(id=session_id)
        _store[session_id] = s
    return s


def set_denomination(session_id: str, denomination_id: str) -> None:
    get_session(session_id).denomination_id = denomination_id


def history_for_prompt(session_id: str) -> list[dict[str, str]]:
    """Summary (as system) + recent verbatim turns, to prepend to the prompt."""
    s = get_session(session_id)
    msgs: list[dict[str, str]] = []
    if s.summary:
        msgs.append(
            {
                "role": "system",
                "content": f"Summary of the conversation so far (for continuity): {s.summary}",
            }
        )
    msgs.extend(s.turns)
    return msgs


def record_turn(session_id: str, user_text: str, assistant_text: str) -> None:
    """Record an exchange; roll up old turns into the summary if needed."""
    s = get_session(session_id)
    s.turns.append({"role": "user", "content": user_text})
    s.turns.append({"role": "assistant", "content": assistant_text})

    if len(s.turns) > _MAX_VERBATIM:
        overflow = s.turns[: len(s.turns) - _KEEP_AFTER_SUMMARY]
        s.turns = s.turns[len(s.turns) - _KEEP_AFTER_SUMMARY :]
        try:
            s.summary = _summarize(s.summary, overflow)
        except Exception as e:  # noqa: BLE001
            print(f"summary update failed: {e}")


def _summarize(prev: str, overflow: list[dict[str, str]]) -> str:
    transcript = "\n".join(
        f"{'User' if t['role'] == 'user' else 'Assistant'}: {t['content']}"
        for t in overflow
    )
    return chat(
        [
            {
                "role": "system",
                "content": "Update a running summary of a Christian-assistant conversation. Keep it "
                "under 120 words, noting the user's topics, any stated denomination/preferences, and "
                "the assistant's tone. Output only the summary.",
            },
            {
                "role": "user",
                "content": f"Previous summary:\n{prev or '(none)'}\n\nNew exchange to fold in:\n{transcript}",
            },
        ],
        temperature=0.2,
        max_tokens=220,
    )
