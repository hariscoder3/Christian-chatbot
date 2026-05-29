"""The chat pipeline. One function ties the layers together so the API route and
the eval harness exercise identical logic:

  input safety -> grounding (retrieval + ref resolution) -> grounded generation
  -> citation verification -> output safety -> memory
"""
from __future__ import annotations

from typing import Any

from collections.abc import Iterator

from app.grounding import CitationCheck, build_grounding, verify_citations
from app.llm import chat, chat_stream
from app.memory import history_for_prompt, record_turn, set_denomination
from app.prompts import build_refusal_prompt, build_system_prompt
from app.safety import screen_input, screen_output

_SAFE_OUTPUT_FALLBACK = (
    "I'm sorry, but I'm not able to share that response. Let's keep our conversation "
    "respectful and grounded in scripture. Is there something else about the Christian "
    "faith I can help you with?"
)


def _citation_dict(c: CitationCheck) -> dict[str, Any]:
    return {"raw": c.raw, "ref": c.ref, "status": c.status, "text": c.text}


def run_chat(
    message: str, session_id: str = "default", denomination_id: str | None = None
) -> dict[str, Any]:
    denomination_id = denomination_id or "neutral"
    if session_id:
        set_denomination(session_id, denomination_id)

    # 1. Input safety screen.
    input_verdict = screen_input(message)

    # 2a. Refusal path — still resolve the user's explicit references so we can
    #     show the real verse (e.g., when they asked to twist it).
    if input_verdict.action == "refuse":
        grounding = build_grounding(message, skip_semantic=True)
        messages = [
            {"role": "system", "content": build_refusal_prompt(input_verdict, denomination_id)},
            {"role": "system", "content": grounding.context_block},
            {"role": "user", "content": message},
        ]
        answer = chat(messages, temperature=0.3, max_tokens=400)
        verification = verify_citations(answer)
        record_turn(session_id, message, answer)
        return {
            "answer": answer,
            "refused": True,
            "citations": [_citation_dict(c) for c in verification.verified],
            "unverifiedRefs": [_citation_dict(c) for c in verification.unverified],
            "retrievedCount": 0,
            "fabricatedUserRef": grounding.has_fabricated_user_ref,
            "safety": {
                "input": {
                    "action": input_verdict.action,
                    "categories": input_verdict.categories,
                    "reason": input_verdict.reason,
                }
            },
        }

    # 2b. Normal path — full grounding + grounded generation.
    grounding = build_grounding(message)
    messages = [
        {"role": "system", "content": build_system_prompt(denomination_id)},
        *history_for_prompt(session_id),
        {"role": "system", "content": grounding.context_block},
        {"role": "user", "content": message},
    ]
    answer = chat(messages, temperature=0.4, max_tokens=1100)

    # 3. Citation verification (hard guarantee against fabricated references).
    verification = verify_citations(answer)
    if verification.has_unverified:
        bad = ", ".join((c.ref or c.raw) for c in verification.unverified)
        answer += (
            f"\n\n_⚠️ Verification note: I could not confirm the following reference(s) "
            f"against the KJV — please double-check: {bad}._"
        )

    # 4. Output safety screen.
    output_verdict = screen_output(answer)
    refused = False
    if output_verdict.action == "refuse":
        answer = _SAFE_OUTPUT_FALLBACK
        refused = True

    # 5. Memory.
    record_turn(session_id, message, answer)

    return {
        "answer": answer,
        "refused": refused,
        "citations": [_citation_dict(c) for c in verification.verified],
        "unverifiedRefs": [_citation_dict(c) for c in verification.unverified],
        "retrievedCount": len(grounding.retrieved),
        "fabricatedUserRef": grounding.has_fabricated_user_ref,
        "safety": {
            "input": {
                "action": input_verdict.action,
                "categories": input_verdict.categories,
                "reason": input_verdict.reason,
            },
            "output": {
                "action": output_verdict.action,
                "categories": output_verdict.categories,
                "reason": output_verdict.reason,
            },
        },
    }


# ─────────────────────────── Streaming variant ───────────────────────────
#
# Same pipeline as run_chat, but yields events for SSE:
#   {"type": "token", "text": "..."}     # incremental chunks
#   {"type": "meta",  ...}               # final metadata (citations, safety, …)
#
# Tokens are streamed live; the post-generation guards (citation verification
# + output safety) run AFTER the stream completes and are reported in the meta
# event. Input safety still runs BEFORE streaming so adversarial prompts are
# refused up front (the refusal text itself is streamed for tone consistency).


def _safety_dict(v) -> dict[str, Any]:
    return {"action": v.action, "categories": v.categories, "reason": v.reason}


def run_chat_stream(
    message: str, session_id: str = "default", denomination_id: str | None = None
) -> Iterator[dict[str, Any]]:
    denomination_id = denomination_id or "neutral"
    if session_id:
        set_denomination(session_id, denomination_id)

    # 1. Input safety screen (blocks before any tokens are sent).
    input_verdict = screen_input(message)

    # 2a. Refusal path — stream the refusal text for tone consistency.
    if input_verdict.action == "refuse":
        grounding = build_grounding(message, skip_semantic=True)
        messages = [
            {"role": "system", "content": build_refusal_prompt(input_verdict, denomination_id)},
            {"role": "system", "content": grounding.context_block},
            {"role": "user", "content": message},
        ]
        parts: list[str] = []
        for token in chat_stream(messages, temperature=0.3, max_tokens=400):
            parts.append(token)
            yield {"type": "token", "text": token}
        answer = "".join(parts)
        verification = verify_citations(answer)
        record_turn(session_id, message, answer)
        yield {
            "type": "meta",
            "refused": True,
            "citations": [_citation_dict(c) for c in verification.verified],
            "unverifiedRefs": [_citation_dict(c) for c in verification.unverified],
            "retrievedCount": 0,
            "fabricatedUserRef": grounding.has_fabricated_user_ref,
            "safety": {"input": _safety_dict(input_verdict)},
        }
        return

    # 2b. Normal path — stream grounded generation.
    grounding = build_grounding(message)
    messages = [
        {"role": "system", "content": build_system_prompt(denomination_id)},
        *history_for_prompt(session_id),
        {"role": "system", "content": grounding.context_block},
        {"role": "user", "content": message},
    ]
    parts = []
    for token in chat_stream(messages, temperature=0.4, max_tokens=1100):
        parts.append(token)
        yield {"type": "token", "text": token}
    answer = "".join(parts)

    # 3. Citation verification. If anything is unverifiable, stream a trailing
    #    warning note so the user sees it directly in the answer area.
    verification = verify_citations(answer)
    if verification.has_unverified:
        bad = ", ".join((c.ref or c.raw) for c in verification.unverified)
        note = (
            f"\n\n_⚠️ Verification note: I could not confirm the following reference(s) "
            f"against the KJV — please double-check: {bad}._"
        )
        yield {"type": "token", "text": note}
        answer += note

    # 4. Output safety screen. Streaming has already shown the content; we can
    #    only flag in retrospect via the meta event (UI shows a "refused" badge).
    output_verdict = screen_output(answer)

    # 5. Memory.
    record_turn(session_id, message, answer)

    yield {
        "type": "meta",
        "refused": output_verdict.action == "refuse",
        "citations": [_citation_dict(c) for c in verification.verified],
        "unverifiedRefs": [_citation_dict(c) for c in verification.unverified],
        "retrievedCount": len(grounding.retrieved),
        "fabricatedUserRef": grounding.has_fabricated_user_ref,
        "safety": {
            "input": _safety_dict(input_verdict),
            "output": _safety_dict(output_verdict),
        },
    }
