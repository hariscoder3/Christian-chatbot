"""Thin client over OpenRouter (OpenAI-compatible).

Covers the modalities this app needs: chat completion, JSON-structured
classification, text embeddings, and Flux image generation. Everything runs on a
single OPENROUTER_API_KEY; embeddings can optionally use a direct OpenAI key.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional, Type, TypeVar

import httpx
from openai import OpenAI
from pydantic import BaseModel

from app.config import config

T = TypeVar("T", bound=BaseModel)

# Explicit HTTP timeouts — the OpenAI SDK default (~600s) lets a single hung
# socket stall the whole pipeline. Fail fast and let max_retries handle blips.
_HTTP_TIMEOUT = httpx.Timeout(60.0, connect=10.0)

_chat_client: Optional[OpenAI] = None
_embed_client: Optional[OpenAI] = None


def _chat() -> OpenAI:
    global _chat_client
    if _chat_client is None:
        _chat_client = OpenAI(
            api_key=config.openrouter_api_key,
            base_url=config.openrouter_base_url,
            default_headers={
                "HTTP-Referer": config.openrouter_referer,
                "X-Title": config.openrouter_title,
            },
            timeout=_HTTP_TIMEOUT,
            max_retries=2,
        )
    return _chat_client


def _embed() -> OpenAI:
    global _embed_client
    if _embed_client is None:
        if config.embed_provider == "openai":
            _embed_client = OpenAI(
                api_key=config.openai_api_key,
                timeout=_HTTP_TIMEOUT,
                max_retries=2,
            )
        else:
            _embed_client = _chat()
    return _embed_client


def chat(
    messages: list[dict[str, str]],
    *,
    model: Optional[str] = None,
    temperature: float = 0.4,
    max_tokens: int = 1200,
) -> str:
    """Plain (non-streaming) chat completion; returns assistant text."""
    res = _chat().chat.completions.create(
        model=model or config.chat_model,
        messages=messages,  # type: ignore[arg-type]
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return (res.choices[0].message.content or "").strip()


def chat_stream(
    messages: list[dict[str, str]],
    *,
    model: Optional[str] = None,
    temperature: float = 0.4,
    max_tokens: int = 1200,
):
    """Streaming chat completion; yields incremental content chunks.

    Used by run_chat_stream so the UI can render tokens live. Post-generation
    guards (citation verification, output safety) still run on the assembled
    answer once the stream completes — see app.pipeline.run_chat_stream.
    """
    stream = _chat().chat.completions.create(
        model=model or config.chat_model,
        messages=messages,  # type: ignore[arg-type]
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    )
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta and delta.content:
            yield delta.content


def chat_json(
    messages: list[dict[str, str]],
    schema: Type[T],
    *,
    model: Optional[str] = None,
    temperature: float = 0.0,
) -> T:
    """Chat completion constrained to JSON, validated against a pydantic model.

    Used by the safety / intent classifiers where reliable structured output from
    a cheap model is required.
    """
    res = _chat().chat.completions.create(
        model=model or config.classifier_model,
        messages=messages,  # type: ignore[arg-type]
        temperature=temperature,
        response_format={"type": "json_object"},
    )
    raw = (res.choices[0].message.content or "{}").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", raw)
        data = json.loads(match.group(0)) if match else {}
    return schema.model_validate(data)


def embed(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts; one vector per input, order preserved."""
    if not texts:
        return []
    res = _embed().embeddings.create(model=config.embed_model, input=texts)
    ordered = sorted(res.data, key=lambda d: d.index)
    return [d.embedding for d in ordered]


def embed_one(text: str) -> list[float]:
    return embed([text])[0]


def generate_image(prompt: str, *, model: Optional[str] = None) -> Optional[str]:
    """Generate an image via OpenRouter's image-output modality (Flux/Gemini).

    DALL-E is not available on OpenRouter, so we use Flux by default. Returns a
    data URL (base64) for the first image, or None. We hit the REST endpoint
    directly because the typed SDK does not expose `modalities` / `images`.
    """
    resp = httpx.post(
        f"{config.openrouter_base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {config.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": config.openrouter_referer,
            "X-Title": config.openrouter_title,
        },
        json={
            "model": model or config.image_model,
            "messages": [{"role": "user", "content": prompt}],
            "modalities": ["image"],
        },
        timeout=120.0,
    )
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    message = (data.get("choices") or [{}])[0].get("message", {})
    images = message.get("images") or []
    if not images:
        return None
    first = images[0]
    # OpenRouter returns image_url.url (data URL) — tolerate a couple of shapes.
    return (first.get("image_url") or {}).get("url") or first.get("url")
