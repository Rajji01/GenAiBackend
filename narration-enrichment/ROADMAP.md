# Narration Enrichment — Track Roadmap (Python / GenAI)

> **What this is:** the ordered plan for the GenAI track (`narration-enrichment/`)
> — where we've been, exactly where we are, what's next. Complements the master
> `Jarvis_GenAI_Path.md` at repo root (which is generic P1-P8 strategy);
> this file is the *implementation-level* roadmap with commit refs + day-by-day
> plans for the next project.
>
> **For a fresh agent:** if you're picking this track up cold, read in this
> order — repo-root `AGENTS.md` → `FILE_GUIDE.md` → `Jarvis_GenAI_Path.md`
> (strategy) → this file (execution) → `narration-enrichment/README.md`
> (build log) → `narration-enrichment/NARRATION_LAB.html` (deep concepts).

---

## Status snapshot

| | |
|---|---|
| **P1 — Transaction Enrichment API** | ✅ **DONE** (Weeks 1–4, last commit `20cb3c6`) |
| **Current position** | P2 in progress — Days 1–5 done + committed + pushed |
| **Next work unit** | P2 Day 6 — eval extension + docs (P2 closeout) |
| **Anchor stack** | FastAPI + Pydantic + Instructor + Gemini + SQLite + pytest |
| **AWS touchpoint so far** | none — deliberate. First touch lands in P2 (S3 for policy docs) |

**P1 recap in one line:** a `POST /enrich` endpoint that turns messy bank
narrations into schema-valid structured JSON, wrapped in production-grade
resilience (retry-with-backoff, in-process rate limiter, correlation IDs,
degrade-not-fail RAG on past narrations, live-verified eval loop). 68 tests,
no network in test suite, LLM + embedding calls mocked at the boundary.

**Non-negotiable rule for this track** (same as ticketing): **live
verification, no cherry-picking.** Every phase claims a capability only
after it's proven against a real Gemini call, real SQLite, real HTTP.

---

## Table of contents

1. [The P1-P8 map](#1-the-p1-p8-map)
2. [P1 build log — what actually shipped](#2-p1-build-log--what-actually-shipped)
3. [P2 daily plan — Transaction + policy RAG](#3-p2-daily-plan--transaction--policy-rag)
4. [P3-P8 outline (from Jarvis_GenAI_Path.md)](#4-p3-p8-outline)
5. [Companion files — which is which](#5-companion-files)
6. [How to use this file](#6-how-to-use-this-file)

---

## 1. The P1-P8 map

Copied verbatim from `Jarvis_GenAI_Path.md` (the master plan) with a
"where you are now" marker overlaid:

| # | Project | New capability | AWS | Microservices | Status |
|---|---------|----------------|-----|---------------|--------|
| P1 | Transaction Enrichment API | Structured output | — | Modular monolith | ✅ **DONE** |
| **P2** | **Transaction + policy RAG** | **Embeddings, retrieval, citations** | **S3 (docs)** | **Modular monolith** | 📍 **NEXT** |
| P3 | Knowledge assistant | Auth, memory, eval pipeline | S3 | Modular monolith | future |
| P4 | Async doc-processing pipeline | Event-driven, idempotency, retries | **SQS, S3, ECS/Lambda, CloudWatch** | **API + Worker split** | future |
| P5 | Tool-calling assistant | Tool loop + guardrails | SQS | API + Worker | future |
| P6 | Agentic workflow (dispute/recon) | Agent loop + "when NOT to agent" | as needed | multi-service | future |
| P7 | Multi-model platform | Routing, fallback, cost/latency, observability | ECS/EKS, RDS+pgvector, Secrets Mgr, API GW, IAM | gateway + provider + retrieval services | future |
| P8 | Capstone platform | Full prod system | full | full | future |

**Rule from the master plan:** don't advance to P(N+1) until P(N)'s
Definition of Done ticks. For P1 that was: schema-valid JSON on sample
txns, clean errors on LLM fail/timeout, key from env, happy + failure
tests, README + `.env.example`, pushed. All green as of `20cb3c6`.

---

## 2. P1 build log — what actually shipped

Compact form of `README.md` §"The week, day by day" and §"Week 2/3/4".
Read the README for the prose story; this table exists so a fresh agent
can find commits and files fast.

### Week 1 — the base service

| Day | Built | Files | Commit |
|---|---|---|---|
| 1 | Raw Gemini SDK call + token accounting (found "thinking tokens eat max_output_tokens" gotcha) | `day1_raw_call.py` | `4cb3d86` |
| 2 | Deliberately broken naive `json.loads()` — 3 real failure shapes reproduced (markdown fence, string-not-float, nested object) | `day2_naive_json.py` | `4cb3d86` |
| 3 | Instructor + Pydantic `TransactionEnrichment` — same casual prompt, now schema-valid | `day3_structured_output.py`, `models.py` | `4cb3d86` |
| 4 | FastAPI service: `POST /enrich`, config-driven timeout/retries, HTTP-level timeout on the client not the route | `main.py`, `service.py`, `config.py` | `4cb3d86` |
| 5 | pytest — unit against schema + integration against real FastAPI with LLM mocked | `tests/test_models.py`, `tests/test_api.py` | `4cb3d86` |
| Wknd | Dockerfile (`ghcr.io/astral-sh/uv`) + docker-compose with healthcheck, verified `docker compose ps` shows `healthy` | `Dockerfile`, `docker-compose.yml` | `4cb3d86` |

### Week 2 — reliability + persistence

- **Phase 1 — Evaluation** (`eval/`): 12-example golden dataset, `run_eval.py`
  reports per-field accuracy + separately the call-failure rate. Uncovered
  live: 5 rpm cap, **20 rpd cap**, and default 10s timeout too tight
  (33% timeout rate) → raised to 20s.
- **Phase 2 — Batch + persistence** (`db.py`): `POST /enrich/batch` (up to
  50, each item isolated), `GET /enrichments`, SQLite repository. Caught
  the "SQLite in-memory tables invisible across pool connections" trap →
  fixed with `StaticPool`. Volume mount added after realizing compose
  file would wipe DB on `down`.
- **Phase 3 — Retry-with-backoff** (`tenacity` in `service.py`): only for
  the exact transient codes hit live (429/503/504), deliberately separate
  from Instructor's own retry which handles bad *shape*, not a failed *call*.
- Commit: `7b92cbe`.

### Week 3 — a real bug + RAG

- **Day 1 bug from a live eval run** (`516ccce`): `InstructorRetryException`
  wraps *every* underlying failure. Exhausted 503s were being reported to
  callers as misleading 422s. Fix: inspect `exc.__cause__` before choosing
  status code. Test built around the actual wrapped-exception shape
  (mocked `_raw_client.models.generate_content`, not `_client.create`).
- **RAG for consistency** (`rag.py`, commit `8fea40d`): embed every
  narration (`gemini-embedding-001`, 256 dims), store vector on the
  Phase-2 row, cosine-similarity retrieve top-3 (floor 0.70), fold into
  prompt as few-shot context. Uses `task_type` asymmetry
  (`RETRIEVAL_DOCUMENT` stored, `RETRIEVAL_QUERY` searched). Live-proved
  end-to-end: seeded a past "UBER TRIP" as `category="transfer"`, fresh
  identical narration flipped from `"other"` (RAG-less) → `"transfer"`.
  RAG degrades-not-fails: embedding failure logs + falls back to
  `context=None`, `/enrich` still returns 200.

### Week 4 — rate limiter + correlation IDs + `/stats`

- **Rate limiter** (`rate_limiter.py`, commit `4899753`): sliding-window
  over the exact live-measured caps (5/min, 20/day). Checked in-process
  *before* the generative call — cheaper and more honest than waiting for
  the provider's own 429. Injectable `time_fn` so tests prove window
  reset without a real 60-second sleep. 8 new tests.
- **Correlation IDs** (`correlation.py`, commit `3f8985d`): Python
  equivalent of the ticketing `CorrelationIdFilter`. Uses
  `contextvars.ContextVar` (per-Task isolation, no `finally { remove() }`
  needed the way Java's `MDC` does). **Bug caught live in this work
  itself:** filter attached via `Logger.addFilter()` silently never runs —
  `Logger.filter()` is only invoked by the logger that *originates* a
  record; propagation to ancestors calls their *handlers*, bypassing the
  ancestor's own filter. Fixed by attaching to the handler
  (`handler.addFilter(...)`). Pinned by two regression tests using an
  *isolated* logger tree (real root already carried the fix — would have
  masked the bug being tested for).
- **`/stats`** (commit `20cb3c6`): DB aggregation (total, avg confidence,
  category breakdown via `GROUP BY`) + read-only peek at rate-limiter
  headroom (`RateLimiter.remaining()` — non-mutating, no slot consumed).
  Empty-table returns `null` not a misleading `0.0`. 9 new tests.

**P1 test count check (last commit `20cb3c6`):** 68 tests green, no
network calls in the suite, LLM + embedding boundaries mocked, DB is
in-memory SQLite via `StaticPool`.

---

## 3. P2 daily plan — Transaction + policy RAG

**Goal:** move from *self-retrieval* (past narrations, P1 Week 3) to
*document-retrieval* — feed the `/enrich` prompt with the relevant
excerpts from a corpus of bank / merchant / category policy documents.
First genuine RAG-over-documents build.

**Design paper:** `P2_DESIGN.md` — read it first. This section is the
day plan; that file is the *why*.

### DoD (Definition of Done)

- [x] `POST /policies/ingest` — upload a policy doc (PDF/txt/md), chunk
      it, embed each chunk, store in a `policy_chunks` table *(Day 3, commit `b72db22`)*
- [x] `/enrich` now retrieves policy chunks alongside past narrations,
      folds both into prompt with distinct labels ("similar past
      classifications" vs "applicable policy excerpts") *(Day 5, this commit)*
- [x] **Citations** — the response schema gains a
      `policy_citations: list[Citation]` field with `doc_id + chunk_id +
      snippet + similarity_score`. Never hallucinated: only chunks
      whose text was actually put in the prompt can be cited *(Day 5 — earned-citations overwrite enforced in `_enrich_and_persist`; regression test `test_llm_provided_citations_are_overwritten_not_appended` proves the LLM cannot smuggle a fake citation past the code)*
- [x] S3-backed storage of the raw documents (first AWS touch on this
      track; SQLite still holds the *chunks + embeddings*) *(Day 4, this commit — bucket creation deferred to user per rule 3-2)*
- [ ] Live-proved end-to-end (like Week 3's RAG proof): seed a policy doc
      that changes classification behavior, run before/after against a
      real narration, capture the difference *(Day 6, pending)*
- [ ] Eval golden dataset extended with 5 policy-driven cases *(Day 6, pending)*
- [x] Tests: chunking is a pure function (unit-test the boundaries) *(Day 2, 13 tests)*,
      retrieval mocks the embedding boundary *(Day 3, 17 tests)*,
      `/policies/ingest` end-to-end with S3 mocked via `moto` *(Day 4, 11 tests — 118 total, up from 68)*
- [ ] `README.md` P2 section + `NARRATION_LAB.html` P2 card *(LAB card landed Days 2/3/4 in this commit; README pass is Day 6)*

### Daily plan (proposal — 6 days across two weekends)

**Day 1 — Design (no code)**
- Write `P2_DESIGN.md`: what a "policy doc" is (concrete examples —
  merchant → category rulebook, subscription-detector heuristics),
  chunking strategy (fixed-size vs semantic — pick + defend), embedding
  model choice (stick with `gemini-embedding-001` for consistency with
  P1 Week 3 RAG), citation contract, S3 vs local-filesystem tradeoff.
- Sequence diagram: `/enrich` request path with policy retrieval woven
  into the existing past-narration retrieval.
- Failure matrix: what happens when S3 is down, embedding is down,
  chunk store is empty, chunk contradicts a past narration.

**Day 2 — Chunker + schema**
- `chunker.py`: pure function `chunk(text, chunk_size, overlap) → list[Chunk]`.
  Unit tests before the API layer touches it.
- SQLAlchemy `PolicyDoc` + `PolicyChunk` models (doc_id, source_uri,
  chunk_id, content, embedding, ingested_at).
- `Citation` Pydantic model + `TransactionEnrichment.policy_citations`
  field.

**Day 3 — Ingest endpoint**
- `POST /policies/ingest`: accepts doc (start with plain text/markdown;
  PDF via `pypdf` if time), stores raw doc, chunks, embeds each chunk
  (batch call to Gemini embed), persists all chunks with vectors.
- Idempotency: same `doc_id` re-ingested = replace, not duplicate.
- Test with real SQLite in-memory + mocked embedding boundary.

**Day 4 — S3 backing**
- Move raw-doc storage from local filesystem to S3
  (`policy-docs/{doc_id}`). Chunks + embeddings stay in SQLite.
- **First AWS touch, and USER-DRIVEN per standing rule §3-3** — Claude
  pairs on `boto3` + config; user creates the actual bucket.
- Tests with `moto` (mock-S3) — no real AWS credentials in CI.

**Day 5 — Retrieval + prompt weaving**
- Extend `rag.py`: `retrieve_policy_chunks(narration, top_k=3, floor=0.65)`
  parallel to the existing `retrieve_past_narrations`.
- Prompt construction in `service.py`: two clearly-labeled blocks
  ("SIMILAR PAST CLASSIFICATIONS" and "APPLICABLE POLICY EXCERPTS")
  fed to Instructor as system-prompt context.
- Response now populates `policy_citations` from ONLY the chunks that
  were actually placed in the prompt. Assertion in the code path, not
  just docs.

**Day 6 — Live proof + eval**
- Seed a policy doc that says "any UBER-prefix narration is
  `transportation`, not `transfer`", ingest it. Run a Uber narration
  before + after — capture the classification flip AND the citation
  pointing to the exact chunk that caused it.
- Extend golden dataset with 5 policy-driven cases. Re-run
  `eval/run_eval.py`; save dated report.
- README + LAB HTML update. Commit. Push (with user OK).

### Concepts to keep tight

- **Chunking is boring on purpose.** Fixed size + overlap first; only
  reach for semantic chunking if the eval shows the boring version
  losing classification accuracy. Same anti-overengineering rule as
  P1's "SQLite over a vector DB".
- **Citations are earned, not decorative.** Only cite chunks that
  actually landed in the prompt. Anything else is a hallucination
  fixed by architecture, not by prompt tweaks.
- **RAG degrades, never fails, the request.** Same rule as P1 Week 3:
  policy retrieval failing = classification runs without policy context,
  not a 500.

---

## 4. P3-P8 outline

From `Jarvis_GenAI_Path.md`, not re-derived here — see that file for
strategic reasoning. Compressed status:

- **P3 — Knowledge assistant** (auth, conversation memory, eval-as-a-system).
  First auth layer, first multi-turn state, first proper eval pipeline
  beyond a golden dataset.
- **P4 — Async doc-processing pipeline** ← **AWS ka asli ghar** per the
  master plan. First real microservice split: API service (queue and
  return) + Worker (embedding/LLM heavy). SQS + DLQ + S3 + ECS/Lambda +
  CloudWatch. First application of ticketing-track's outbox learnings
  in Python. **User-owned per §3-2 (AWS work is Rajat's).**
- **P5 — Tool-calling assistant** (Python + Spring AI port). Second of
  the two Spring AI ports (P1 was the first).
- **P6 — Agentic workflow.** Interview line: "when NOT to agent." Loop
  control, guardrails, cost bound.
- **P7 — Multi-model platform.** Routing, fallback, RDS+pgvector,
  Secrets Manager (no more `.env` keys), API Gateway. First multi-service
  split with a gateway.
- **P8 — Capstone.** Full stack, CI/CD, end-to-end system design.

**Rule (from master plan):** P4 is where AWS really lives. Don't sprinkle
random AWS bits into P1-P3 to "get exposure" — each service is learned
by using it in a project that needs it, not by touching it for its own
sake.

---

## 5. Companion files

| File | Category | Purpose |
|---|---|---|
| `README.md` | 📖 Build log | Prose day-by-day story of Weeks 1–4 + engineering decisions. **Read this if you want the story.** |
| `LEARNING_NOTES.md` | 📖 Prose revision | Self-check questions per day, no answers by design. **Revision tool.** |
| `NARRATION_LAB.html` | 🔨 Showcase HTML | Deep concept + build log in mint/teal Narration Lab design system. **Portfolio-shape.** |
| `NARRATION_STUDY.html` | 📘 Personal learning | Rajat's Q&A journal for narration — scaffolded, filled in as teaching-mode sessions happen. **Study tool, distinct from portfolio.** |
| `ROADMAP.md` (this file) | 🗺️ Track roadmap | Where you are, what's next, day-plan for the next project. |
| `P2_DESIGN.md` | 📝 Design + Qs | Design paper for the next work unit (RAG over policy docs). |
| `src/narration_enrichment/**.py` | ⚙️ Code | Production source. `main.py`, `service.py`, `models.py`, `db.py`, `rag.py`, `rate_limiter.py`, `correlation.py`, `config.py`, `schemas.py` + the three day-N scratch scripts kept as historical record. |
| `tests/**` | ⚙️ Tests | 68 tests, pytest, no network. |
| `eval/**` | ⚙️ Eval harness | 12-example golden dataset + `run_eval.py`. Costs real API quota — run manually. |
| `Dockerfile`, `docker-compose.yml`, `pyproject.toml`, `uv.lock` | ⚙️ Config | Local run. |

---

## 6. How to use this file

**Reading it now, mid-project:**
- Section 1 tells you where P1 sits in the P1-P8 arc.
- Section 2 is the compact "what shipped" table — trace any commit
  back to what it covered.
- Section 3 is your day-by-day plan for the next work unit. Do NOT
  advance to P3 until P2's DoD ticks. Update section 3's checkboxes
  as work lands.
- Section 4 is the far-horizon view.

**Updating this file:**
- When P2 completes → move it to the "DONE" pattern of P1 (add a
  build-log table in section 2). Rewrite section 3 for P3.
- Any user-facing directive I'm given about this track ("prefer X",
  "don't reach for Y") gets captured in the appropriate section or in
  `AGENTS.md` §3, per standing rule §3-9.

**For a fresh session:**
- If the top of section 1 doesn't show which project is 📍 NEXT — this
  file is stale. Fix it before writing any code.

---

*Companion to `Jarvis_GenAI_Path.md` (strategy) and repo-root
`AGENTS.md` §4 (portable state). Update after every finished work unit.*
