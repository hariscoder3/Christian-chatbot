# Architecture Note — Grounded Faith Assistant

## 1. Goal & priorities

A Christianity-focused assistant that (a) answers faith questions, (b) generates
Christian content, (c) generates reverent images, while (d) **never fabricating
scripture**, (e) refusing hateful/heretical/manipulative requests, and (f) handling
denominational nuance gracefully. Per the brief, we optimise for **grounding
quality, hallucination prevention, safety, and edge-case handling** over UI polish.

## 2. System overview

```
┌────────────┐   HTTP/JSON   ┌──────────────────────── FastAPI (Python) ───────────────────────┐
│ Next.js UI │ ────────────▶ │  /api/chat   /api/image   /api/verse                              │
│ (React/TS) │               │                                                                    │
└────────────┘               │  chat pipeline:                                                    │
                             │   1 input safety screen  ──────────────┐ (refuse → graceful reply) │
                             │   2 grounding: Pinecone retrieval + user-reference resolution      │
                             │   3 grounded generation (OpenRouter chat, denomination-aware)      │
                             │   4 citation verification vs local KJV (flag/strip fabrications)   │
                             │   5 output safety screen                                            │
                             │   6 rolling-summary memory                                          │
                             │  image flow: prompt screen → reverent rewrite → Flux (OpenRouter)  │
                             └────────────────────────────────────────────────────────────────────┘
        external: OpenRouter (chat · classifiers · embeddings · Flux)   ·   Pinecone (verse vectors)
        local:    data/bible/kjv.json  (canonical text — source of truth for lookup + verification)
```

**Why a split stack:** the frontend was specified as Next.js/React; the backend is
Python/FastAPI (requested). They communicate over a small JSON API with CORS, so
each can be deployed and scaled independently.

## 3. The grounding / anti-hallucination strategy (core)

Fabricated verses are the central risk, so we defend in five layers rather than
trusting prompt instructions alone:

| Layer | Mechanism | Location |
|------|-----------|----------|
| 1. No parametric scripture | System prompt forbids quoting verse text from memory; only `CONTEXT` verses may be quoted. | `prompts.py` |
| 2. Retrieve-then-generate | Query is embedded; Pinecone returns top-k verses; **text is re-read from the local KJV**, not from the vector store. | `retrieval.py` |
| 3. Citation verification | After generation, every emitted reference is parsed and checked against the canonical KJV; unverifiable refs are flagged in-line and surfaced to the UI. | `grounding.verify_citations` |
| 4. Inbound fake/misquote detection | References the user supplies are resolved; invalid books (`2 Hesitations`) and out-of-range verses (`John 3:99`) are marked NOT-FOUND in `CONTEXT` so the model corrects them. | `grounding.build_grounding`, `scripture.py` |
| 5. Abstain over invent | Empty retrieval → the model is instructed to say so; historical claims are hedged and separated from scripture. | `prompts.py` |

The reference parser (`scripture.extract_references`) is deliberately conservative:
a candidate must be **capitalized** (references are proper nouns), so prose like
"the ratio is 1:2" or "meet at 1:30" is never mistaken for a citation, while
fabricated-but-reference-shaped tokens (`2 Hesitations 4:12`) are still surfaced.

**Key property:** the verification path (layers 3–4) is **fully local and
deterministic** — it never calls the network — so the guarantee holds even if
OpenRouter/Pinecone are degraded. The committed `kjv.json` is the single source of
truth; Pinecone metadata is used only to *identify* a verse, never as its text.

## 4. Safety design

A single cheap classifier (`safety.py`) scores text on **two axes at once**:

- **Generic harm:** hate, harassment, violence, sexual, self-harm, illicit.
- **Religion-specific adversarial intent:** scripture manipulation, ideological
  rewrites, religious hate, extremism, jailbreak, fabrication-demand.

Generic moderation alone misses the domain attacks in the brief ("rewrite Romans to
support ideology X"), which is why a custom classifier is necessary — and since we
need it anyway, it doubles as our moderation layer (no separate OpenAI moderation
key required). Screening runs on **input and output** (catching a jailbroken model),
and **fails closed** (classifier error ⇒ refuse). Refusals are generated in the
assistant's pastoral voice and, where useful (e.g. "rewrite this verse"), show the
*real* text instead. Image prompts get a dedicated classifier
(`safety.screen_image_prompt`) tuned for subtle violations (degrading/mocking sacred
figures, weaponised imagery, deepfakes).

## 5. Denomination awareness

`denominations.py` encodes Catholic / Protestant / Orthodox / neutral lenses
(canon differences, distinctives, authoritative sources, framing). The selected lens
is injected into the system prompt; the assistant presents the chosen tradition's
view **and** neutrally flags where traditions diverge, never asserting a contested
position as universal fact. Difficult-theology questions follow a "graceful handling"
protocol: acknowledge complexity, present the range of mainstream views with
scripture, defer pastoral crises to clergy/professionals.

## 6. Conversation memory

`memory.py` keeps recent turns verbatim for tone/topic continuity and
compresses older turns into a rolling LLM summary so context stays bounded. Demo-
scale (in-process); the same interface maps to SQLite/Redis for production.

## 7. Evaluation methodology

`eval/run_eval.py` runs the **same pipeline** the API uses over labelled cases and
scores: grounding rate, **citation accuracy** (% answers with zero unverifiable
refs), refusal correctness (adversarial), fake-verse detection, over-refusal (we
explicitly test that sincere hard questions are *not* blocked), and image-policy
accuracy. Checks are programmatic where possible (citation status is verifiable;
refusal/fake-flag are booleans from the pipeline); genuinely subjective items are
marked qualitative rather than faked into a pass/fail.

## 8. Key engineering decisions & trade-offs

- **Single-key OpenRouter** for chat/classifiers/embeddings/images → simple ops and
  billing. Cost: no free moderation endpoint, so moderation is an LLM classifier
  (slightly higher latency) — acceptable since the domain classifier is required
  anyway.
- **Flux over DALL-E** because DALL-E isn't on OpenRouter; we own the image-safety
  layer (screen + reverent rewrite), a stronger safety demonstration than relying on
  a vendor policy.
- **Pinecone (managed)** keeps the backend stateless and scales past Bible-size
  (e.g. adding commentaries) without re-architecting.
- **Local KJV as source of truth** decouples *verification* from *retrieval*, so a
  retrieval miss can never produce a wrong-but-confident citation.
- **Verification in code, behaviour in prompts** — guarantees that must hold (no
  fabricated refs, fail-closed safety) live in deterministic code; tone and nuance
  live in prompts.

## 9. Known limitations / future work

- Citations are verified for **existence** (reference resolves to a real verse); we
  surface the canonical text for the user to compare, but don't yet hard-fail on a
  *paraphrase* the model attributes as a verbatim quote. Token-overlap scoring against
  the canonical text is the natural next step.
- KJV-only canon; Catholic/Orthodox deuterocanonical books are described but not yet
  citable (flagged in the denomination notes).
- Memory is in-process; multi-user persistence needs a store swap.
- Two classifier calls + generation add latency; production would cache the input
  screen and/or use a smaller distilled classifier.
