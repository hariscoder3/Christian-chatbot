# ✝️ Grounded Faith Assistant

A Christianity-focused AI assistant that answers questions, generates Christian
content, and creates reverent Christian images — while staying **grounded in actual
scripture**, refusing to **hallucinate verses**, and **screening out**
hateful / heretical / manipulative requests.

> Built to showcase grounding strategy, hallucination prevention, AI-safety
> thinking, and architecture — not UI polish.

- **Frontend:** Next.js / React (TypeScript)
- **Backend:** Python / FastAPI
- **LLM + embeddings + image gen:** OpenRouter (single key)
- **Vector store:** Pinecone (managed serverless)
- **Canonical text:** public-domain KJV, shipped locally as the source of truth

---

## Why this isn't "just a chatbot"

The hard problem is **never letting a fabricated Bible verse reach the user**. We
solve it with a 5-layer grounding strategy (see [ARCHITECTURE.md](ARCHITECTURE.md)):

1. **No parametric scripture** — the model may only quote verses from a retrieved
   `CONTEXT` block, never from memory.
2. **Retrieve-then-generate** — semantic search (Pinecone) supplies the exact
   canonical verses for the topic.
3. **Post-hoc citation verification** — every reference the model emits is
   re-checked against the local KJV; unverifiable ones are flagged before display.
4. **Fake/misquote detection (inbound)** — references the *user* supplies are
   validated; `2 Hesitations 4:12` and `John 3:99` are caught and corrected.
5. **"I don't know" over invention** — if nothing relevant is retrieved, the model
   says so instead of fabricating.

A **safety layer** wraps the whole pipeline (input + output classifiers + an
image-prompt screen) covering generic harm *and* religion-specific attacks
("rewrite Romans to support ideology X", hateful sermons, jailbreaks).

---

## Architecture at a glance

```
Browser ─▶ Next.js UI ──HTTP──▶ FastAPI ─┬─ input safety screen
(chat / image /                          ├─ grounding (Pinecone retrieval + ref resolution)
 denomination)                           ├─ grounded generation (OpenRouter chat)
                                         ├─ citation verification (local KJV)
                                         ├─ output safety screen
                                         └─ rolling-summary memory
                         image path: prompt screen ▶ reverent rewrite ▶ Flux (OpenRouter)
```

---

## External services you must provision

| Service | Required | Notes |
|---------|----------|-------|
| **OpenRouter** | ✅ | One key powers chat, classifiers, embeddings, and Flux image gen. Get a key + a few $ of credits at https://openrouter.ai/keys |
| **Pinecone** | ✅ | Free serverless tier is enough. The build script auto-creates the index (dim 1536, cosine). https://app.pinecone.io |
| OpenAI | ⬜ | Optional embeddings fallback (`EMBED_PROVIDER=openai`). |

> **Note:** DALL-E is *not* available via OpenRouter, so images use **Flux** (also
> on the OpenRouter key). Verify model slugs at https://openrouter.ai/models.

---

## Setup

### Prerequisites
- Node.js 20+  ·  Python 3.11+

### 1. Backend (Python / FastAPI)

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # then fill in OPENROUTER_API_KEY and PINECONE_API_KEY

# The canonical KJV (data/bible/kjv.json) is committed. Build the vector index once:
python scripts/build_index.py     # embeds ~31k verses, auto-creates the Pinecone index

# Run the API
uvicorn app.main:app --reload --port 8000
```

> Re-deriving the Bible data from scratch (optional): download the raw KJV to
> `backend/data/bible/kjv_raw.json`, then `python scripts/prepare_bible.py`.
> Source: https://github.com/thiagobodruk/bible (`json/en_kjv.json`).

### 2. Frontend (Next.js)

```bash
# from repo root
npm install
cp .env.local.example .env.local   # NEXT_PUBLIC_API_BASE=http://localhost:8000
npm run dev                         # http://localhost:3000
```

---

## Evaluation

A small labelled dataset + harness scores the dimensions the brief cares about.

```bash
cd backend && source .venv/bin/activate
python eval/run_eval.py
```

Reports: **grounding rate**, **citation accuracy** (% answers with zero
unverifiable refs), **refusal correctness** (adversarial cases), **fake-verse
detection**, **over-refusal**, and **image-policy** accuracy.

Datasets:
- `backend/eval/dataset.jsonl` — factual, topical, denominational, difficult-theology, fake-verse, contradictory, hallucinated-history
- `backend/eval/adversarial.jsonl` — jailbreaks, ideological rewrites, hateful/extremist, fabrication demands
- `backend/eval/image-cases.jsonl` — safe vs subtly-violating image prompts

---

## Project structure

```
app/                      Next.js frontend (chat + image + denomination UI)
backend/
  app/
    config.py             env-driven settings (single OpenRouter key + Pinecone)
    llm.py                OpenRouter: chat · chat_json · embed · generate_image
    scripture.py          canonical KJV: books · lookup · reference parsing (source of truth)
    retrieval.py          Pinecone client + semantic search
    grounding.py          build_grounding (context) + verify_citations (guardrail)
    safety.py             input/output classifiers + image-prompt screen
    prompts.py            system · refusal · image-rewrite prompts
    denominations.py      Catholic / Protestant / Orthodox / neutral
    memory.py             rolling-summary session memory
    pipeline.py           run_chat orchestrator
    main.py               FastAPI app (/api/chat, /api/image, /api/verse)
  scripts/                prepare_bible.py · build_index.py
  eval/                   dataset + adversarial + image cases + run_eval.py
  data/bible/kjv.json     committed canonical KJV (source of truth)
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the design rationale and trade-offs.
