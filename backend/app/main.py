"""FastAPI backend for the Grounded Faith Assistant.

Endpoints mirror the original design: /api/chat, /api/image, /api/verse.
Handlers are sync `def` so FastAPI runs them in a threadpool (the LLM/Pinecone
SDKs are synchronous).
"""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()  # load .env before importing config-dependent modules

import json  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from app.config import config  # noqa: E402
from app.llm import generate_image  # noqa: E402
from app.pipeline import run_chat, run_chat_stream  # noqa: E402
from app.prompts import rewrite_image_prompt  # noqa: E402
from app.scripture import (  # noqa: E402
    parse_reference,
    reference_exists,
    resolve_verses,
)
from app.safety import screen_image_prompt  # noqa: E402

app = FastAPI(title="Grounded Faith Assistant API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.frontend_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    sessionId: str = "default"
    denominationId: str | None = None


class ImageRequest(BaseModel):
    prompt: str
    denominationId: str | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/chat")
def chat_endpoint(req: ChatRequest) -> dict:
    """Non-streaming JSON chat (curl-friendly; used by the eval harness)."""
    message = req.message.strip()
    if not message:
        return {"error": "message is required."}
    try:
        return run_chat(message, req.sessionId or "default", req.denominationId)
    except Exception as e:  # noqa: BLE001
        print(f"/api/chat error: {e}")
        return {"error": str(e)}


@app.post("/api/chat/stream")
def chat_stream_endpoint(req: ChatRequest):
    """Streaming chat via SSE. Yields {type:'token',text:'…'} events as the
    answer is generated, then a final {type:'meta',…} with citations + safety."""
    message = req.message.strip()
    if not message:
        return {"error": "message is required."}

    def event_source():
        try:
            for event in run_chat_stream(
                message, req.sessionId or "default", req.denominationId
            ):
                yield f"data: {json.dumps(event)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:  # noqa: BLE001
            print(f"/api/chat/stream error: {e}")
            yield f'data: {json.dumps({"type": "error", "message": str(e)})}\n\n'

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/image")
def image_endpoint(req: ImageRequest) -> dict:
    prompt = req.prompt.strip()
    if not prompt:
        return {"error": "prompt is required."}
    try:
        # 1. Safety pre-check on the raw user idea.
        verdict = screen_image_prompt(prompt)
        if verdict.action == "refuse":
            return {
                "refused": True,
                "reason": verdict.reason,
                "categories": verdict.categories,
            }
        # 2. Rewrite into a reverent, descriptive, safe prompt.
        safe_prompt = rewrite_image_prompt(prompt, req.denominationId)
        # 3. Generate via OpenRouter (Flux).
        data_url = generate_image(safe_prompt)
        return {
            "refused": False,
            "originalPrompt": prompt,
            "safePrompt": safe_prompt,
            "imageUrl": data_url,
        }
    except Exception as e:  # noqa: BLE001
        print(f"/api/image error: {e}")
        return {"error": str(e)}


@app.get("/api/verse")
def verse_endpoint(ref: str = "") -> dict:
    ref = ref.strip()
    if not ref:
        return {"error": "ref is required."}
    parsed = parse_reference(ref)
    if parsed is None:
        return {"valid": False, "reason": "Unrecognized book or reference format."}
    if not reference_exists(parsed):
        return {"valid": False, "reason": "That reference does not exist in the canon."}
    verses = [
        {"ref": v.ref, "book": v.book, "chapter": v.chapter, "verse": v.verse, "text": v.text}
        for v in resolve_verses(parsed)
    ]
    return {"valid": True, "verses": verses}
