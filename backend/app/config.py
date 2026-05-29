"""Central configuration.

Everything runs on a single OpenRouter key (+ Pinecone). Models are env-driven so
nothing is hardcoded. See .env.example for what each value means.
"""
from __future__ import annotations

import os


def _required(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(
            f"Missing required env var {name}. Copy .env.example to .env and fill it in."
        )
    return val


def _opt(name: str, default: str) -> str:
    return os.environ.get(name) or default


class Config:
    # ---- OpenRouter (chat, classifiers, embeddings, image gen) ----
    @property
    def openrouter_api_key(self) -> str:
        return _required("OPENROUTER_API_KEY")

    openrouter_base_url = _opt("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    openrouter_referer = _opt("OPENROUTER_SITE_URL", "http://localhost:3000")
    openrouter_title = _opt("OPENROUTER_SITE_NAME", "Grounded Faith Assistant")

    # ---- Optional direct-OpenAI fallback for embeddings ----
    @property
    def openai_api_key(self) -> str:
        return os.environ.get("OPENAI_API_KEY", "")

    # ---- Pinecone ----
    @property
    def pinecone_api_key(self) -> str:
        return _required("PINECONE_API_KEY")

    pinecone_index = _opt("PINECONE_INDEX", "bible-kjv")

    # ---- Models (verify slugs at https://openrouter.ai/models) ----
    chat_model = _opt("CHAT_MODEL", "openai/gpt-4.1-mini")
    classifier_model = _opt("CLASSIFIER_MODEL", "openai/gpt-4o-mini")
    embed_model = _opt("EMBED_MODEL", "openai/text-embedding-3-small")
    image_model = _opt("IMAGE_MODEL", "black-forest-labs/flux.2-klein-4b")
    embed_dim = int(_opt("EMBED_DIM", "1536"))

    # "openrouter" (default) routes embeddings through OpenRouter; "openai" uses
    # OPENAI_API_KEY directly as a fallback.
    embed_provider = _opt("EMBED_PROVIDER", "openrouter")

    # ---- Retrieval tuning ----
    retrieval_top_k = int(_opt("RETRIEVAL_TOP_K", "8"))
    retrieval_min_score = float(_opt("RETRIEVAL_MIN_SCORE", "0.15"))

    # CORS origins for the Next.js frontend.
    frontend_origins = _opt(
        "FRONTEND_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")


config = Config()
