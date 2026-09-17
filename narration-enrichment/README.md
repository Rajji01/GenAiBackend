# Narration Enrichment

Turns a messy bank transaction narration into structured, validated JSON —
using an LLM, but never trusting it blindly.

```
"UPI/P2M/509912345678/PAYTM/SWIGGY BANGALORE/Payment"
        │
        ▼
{
  "merchant": "Swiggy",
  "category": "food_delivery",
  "transaction_type": "UPI",
  "confidence": 0.95
}
```

## Problem

Bank statement narrations are inconsistent, provider-specific strings —
nobody hands you clean sentences. Asking an LLM to "extract this as JSON"
and parsing the response with `json.loads()` looks fine until it isn't:
the model wraps its answer in a ` ```json ` fence, or returns
`"confidence": "High"` instead of a number, or invents a completely
different shape. All three of these are things this project actually
reproduced against a real model, not hypotheticals (see Day 2 below).

The fix isn't a smarter prompt — it's validating untrusted output at the
boundary, the same way you'd validate untrusted user input.

## Architecture

```
Client
  │  POST /enrich {"narration": "..."}
  ▼
FastAPI (main.py)
  │  EnrichRequest (Pydantic) — rejects bad input before the LLM is ever called
  ▼
service.py
  │  Instructor-wrapped Gemini client, response_model=TransactionEnrichment
  ▼
Gemini (gemini-3.6-flash)
  │  forced through the schema via native function-calling (Mode.TOOLS),
  │  not by hoping the model writes correct JSON prose
  ▼
TransactionEnrichment (Pydantic) — validated, typed, or a clean 422/504/500
```

Config (model name, timeout, retries, API key) lives in `config.py`,
read once from the environment — nothing is hardcoded in the request path.

## Setup

```bash
uv sync
cp .env.example .env   # then put your real GEMINI_API_KEY in .env
```

Get a free Gemini API key at https://aistudio.google.com (no credit card
needed).

## Run

```bash
uv run uvicorn narration_enrichment.main:app --reload
```

Then either:
- open http://127.0.0.1:8000/docs for interactive Swagger UI, or
- `curl -X POST http://127.0.0.1:8000/enrich -H "Content-Type: application/json" -d '{"narration":"UPI/P2M/509912345678/PAYTM/SWIGGY BANGALORE/Payment"}'`

## Test

```bash
uv run pytest -v
```

59 tests, no network calls, no API key required — the LLM and the
embedding calls are both mocked out for every test that goes through the
HTTP layer, and the database is swapped for an in-memory SQLite instance.

## Evaluate (costs real API quota — run manually, not in CI)

```bash
uv run python eval/run_eval.py
```

Runs the real pipeline (real Gemini calls) against `eval/golden_dataset.json`
— 12 hand-labeled bank narrations — and reports per-field accuracy,
separately from the call-failure rate (timeouts/quota are a *reliability*
finding, not a *correctness* one). A dated JSON report is saved under
`eval/results/`. Run this whenever the prompt, schema, or model changes.

## Batch + persistence

```bash
curl -X POST http://localhost:8000/enrich/batch \
  -H "Content-Type: application/json" \
  -d '{"narrations": ["UPI/P2M/.../SWIGGY/Payment", "POS .../AMAZON.IN/..."]}'

curl http://localhost:8000/enrichments
```

`/enrich` and `/enrich/batch` both persist every successful result to
SQLite (`db.py`); `/enrichments` lists what's stored. A bad item inside a
batch is isolated — it's recorded as a failure in that item's slot, the
rest of the batch still completes.

## RAG (retrieval-augmented consistency)

No separate endpoint — it's transparent inside `/enrich` and
`/enrich/batch`. Every call now:

1. embeds the incoming narration and searches past persisted enrichments
   for similar ones (cosine similarity, floor 0.70, top 3),
2. if any are found, folds them into the prompt as "here's how similar
   past narrations were classified",
3. embeds and stores the new narration's vector alongside its result, so
   it can itself be retrieved by future calls.

The first calls against an empty database get no context (nothing honest
to retrieve yet) and behave exactly like Week 1/2. As the table fills up,
the model is shown its own past decisions for genuinely similar
narrations, which is what makes classification more consistent over time
instead of independently re-guessing every time. If the embedding call
itself fails, `/enrich` still returns its normal result with no context —
this is an enhancement, not a dependency.

## Rate limiting

The free tier's real limits (measured live in Phase 1, not from
documentation) are two separate caps: **5 requests/minute** and **20
requests/day**. `rate_limiter.py` enforces both locally, in front of the
actual generative call, so a request that would exceed either one is
rejected instantly with `429` and a `Retry-After` header — no wasted
round trip to the provider, and no burning through the *daily* cap by
retrying something that was never going to succeed today.

```bash
curl -i -X POST http://localhost:8000/enrich \
  -H "Content-Type: application/json" -d '{"narration":"..."}'
# once the limit is hit:
# HTTP/1.1 429 Too Many Requests
# Retry-After: 47
# {"detail":"Rate limit exceeded (per_minute). Retry after 47s."}
```

In `/enrich/batch`, a narration that lands after the limiter trips is
isolated the same way a provider failure already is — reported as that
one item's failure (`error: "RateLimitExceededError"`), the rest of the
batch is unaffected.

## Run in Docker

```bash
cp .env.example .env   # then put your real GEMINI_API_KEY in .env
docker compose up --build
```

Same two checks as above, just against the container:

```bash
curl http://localhost:8000/health
curl -X POST http://localhost:8000/enrich -H "Content-Type: application/json" \
  -d '{"narration":"UPI/P2M/509912345678/PAYTM/SWIGGY BANGALORE/Payment"}'
```

`docker compose ps` should show the service as `healthy` within ~10s.

## Engineering decisions

- **Gemini over Anthropic/OpenAI** — the original plan was Anthropic, but
  the available account was tied to a work email; switched to Gemini's
  free tier (Google AI Studio, no card needed) to keep this project
  entirely separate from anything work-related. Instructor abstracts the
  provider anyway — swapping providers later is a `service.py`-only change.
- **`response_model` + Instructor's `Mode.TOOLS`, not prompt engineering** —
  Day 2 showed that even a well-worded prompt can't guarantee shape;
  Day 3 showed that forcing the shape through the provider's native
  function-calling can. The retry (`max_retries=3`) is a safety net for
  when even that isn't enough, not the primary defense.
- **No `odds`/free-text fields the model can shape however it wants** —
  every field in `TransactionEnrichment` has an explicit type and, for
  `category`, an explicit closed set (`Literal[...]`). An open `str`
  field would have let the "confidence as a nested object" failure mode
  back in through the side door.
- **Timeout on the HTTP client, not `asyncio.wait_for` around the route** —
  `genai.Client(http_options=HttpOptions(timeout=...))` bounds the actual
  network call. Wrapping the route handler instead would let the request
  return "on time" while the provider call kept running in the
  background, still burning cost.
- **Own persisted data as the RAG knowledge base, not a vector database** —
  Phase 2 already persists every enrichment. Reusing that as the retrieval
  corpus (an `embedding` column on the same table, cosine similarity in
  plain Python) gets few-shot consistency without a new infrastructure
  dependency at this project's scale. Embeddings use `task_type` asymmetry
  (`RETRIEVAL_DOCUMENT` for what's stored, `RETRIEVAL_QUERY` for what's
  searched) — skipping that distinction quietly degrades similarity scores
  without ever raising an error.
- **RAG retrieval and storage both degrade, never fail, the request** —
  both embedding calls in `_enrich_and_persist` are wrapped in their own
  try/except that logs and falls back to `context=None` /
  `embedding=None`. A broken embedding call should cost this one row's
  future retrievability, not turn a working `/enrich` into an outage.
  Verified live by mocking `embed_text` to raise and confirming `/enrich`
  still returns 200.
- **In-process sliding-window limiter, not Redis-backed** — this service
  runs as one process; a distributed rate limiter would solve a problem
  this deployment doesn't have. Same reasoning as reusing SQLite for RAG
  instead of a vector database. The clock is injectable
  (`time_fn=time.monotonic` by default) specifically so tests can prove a
  60-second window resets without a real 60-second sleep.
- **Reject locally before the call, don't rely on retrying the provider's
  429** — Phase 3's retry-with-backoff already handles a transient 429
  gracefully, but retrying still spends a real call to rediscover a limit
  that's already known locally, and the *daily* cap doesn't recover
  within any retry window. Checking first is strictly better: free,
  instant, and the caller gets an honest `Retry-After` instead of
  watching three retries fail identically.
- **PII/prompt content logged at DEBUG only, metadata at INFO** — a bank
  narration can carry account fragments or names. Verified live: the
  running server's INFO logs contain `narration_length=51`, never the
  narration text itself.
- **Exceptions mapped by type, not by string-matching messages** —
  `InstructorRetryException` → 422, `httpx.TimeoutException` → 504,
  anything else → a generic 500 that never echoes the real exception
  message back to the caller. The same principle as the Java project's
  `GlobalExceptionHandler`, in a different language.
- **A logging filter belongs on the handler, not the logger** — found the
  hard way (see Week 4 below): `Logger.addFilter()` only affects records
  that logger itself originates, not records from child loggers merely
  propagating through it. `Handler.addFilter()` is the one that actually
  applies regardless of origin, since every propagated record still has
  to pass through the handler it ultimately reaches.

## The week, day by day

- **Day 1** — wired the raw Gemini SDK, made one call, looked at the actual
  request payload and token usage. Found that `gemini-3.6-flash` spends
  "thinking" tokens out of the same `max_output_tokens` budget as the
  visible answer — a low budget silently truncated the response.
- **Day 2** — deliberately broke the naive approach: asked for JSON with a
  casual prompt, parsed the raw text with `json.loads()`. All three
  reproductions failed for three different real reasons: a markdown
  fence, `"confidence": "High"` (string, not float), and a fully nested
  object where a scalar was expected.
- **Day 3** — same prompts, same narrations, wrapped the call with
  [Instructor](https://python.useinstructor.com/) and a `TransactionEnrichment`
  Pydantic model. All three came back clean, typed, validated — because
  Instructor forces the shape via the model's native tool-calling, it
  doesn't just hope and parse.
- **Day 4** — built the FastAPI service: `POST /enrich`, config-driven
  model/timeout/retries, a real HTTP-level timeout, and logging discipline
  (narration/PII only at DEBUG, never INFO).
- **Day 5** — tests: a unit-level suite against the Pydantic schema itself,
  and an integration suite against the real FastAPI app with the LLM
  mocked out (no network, no cost, deterministic).

- **Weekend** — Dockerfile (`ghcr.io/astral-sh/uv` base image, dependency
  layer cached separately from app code) and `docker-compose.yml` with a
  healthcheck. Verified end to end: built the image, ran it, hit
  `/health` and `/enrich` against the actual container (not just the
  local `uvicorn --reload` process), confirmed `docker compose ps` shows
  `healthy`.

## Week 2

- **Phase 1 — Evaluation** — a 12-example golden dataset and `eval/run_eval.py`.
  Running it uncovered two real reliability limits on the free tier: a
  5 requests/minute cap, and a **20 requests/day** cap — both discovered by
  running the eval unpaced and reading the actual `429`/quota error, not
  from documentation. Also found the default 10s timeout was too tight for
  a reasoning model under real network conditions (33% timeout rate) and
  raised it to 20s based on that measurement.
- **Phase 2 — Batch + persistence** — `POST /enrich/batch` (up to 50
  narrations, each isolated so one failure doesn't sink the batch),
  `GET /enrichments`, and a SQLite-backed repository layer (`db.py`).
  Hit a classic SQLite-in-memory testing gotcha (tables created on one
  pooled connection, invisible to the next) — fixed with SQLAlchemy's
  `StaticPool`. Added a Docker volume mount after realizing the original
  compose file would have silently wiped the database on every
  `docker compose down` — verified live: a row saved before `down` was
  still there after `up`.
- **Phase 3 — Production reliability** — retry-with-backoff (`tenacity`),
  but *only* for the exact transient codes hit live in Phase 1 (429, 503,
  504) — deliberately separate from Instructor's own retry, which handles
  bad *shape*, not a failed *call*. A non-transient error (400, 404) is
  never retried, since it would just fail identically three times.

## Week 3

- **Day 1 — a real bug from a live eval run** — `InstructorRetryException`
  wraps *every* underlying failure, including a transient provider error
  that had already exhausted `service.py`'s own retry — not just a genuine
  shape/validation failure. An exhausted 503 was being reported to the
  caller as a misleading 422. Fixed by inspecting `exc.__cause__` before
  choosing the status code, confirmed with a test built around the actual
  wrapped-exception shape (mocking the real API boundary,
  `_raw_client.models.generate_content`, not `_client.create` directly).
- **RAG** — `rag.py` embeds every narration (`gemini-embedding-001`, 256
  dims) and stores the vector alongside the row Phase 2 already persists.
  A new narration is embedded as a query, compared by cosine similarity
  against past rows, and the closest matches (above a similarity floor,
  capped to top 3) are folded into the prompt as few-shot context. Proved
  live, not just by unit test: seeding a past "UBER TRIP PAYMENT" row as
  `category="transfer"` flipped a fresh identical narration's
  classification from `"other"` (the original, RAG-less finding) to
  `"transfer"` — a genuinely clean before/after showing the model
  following its own retrieved history. A second live case (a fictional
  local vendor already classified correctly without help) showed no
  difference, reported as-is rather than swapped out for a flattering
  example.

## Week 4

- **Rate limiting** — `rate_limiter.py`, a sliding-window limiter over
  the exact two caps Phase 1 measured live (5/min, 20/day), checked
  in-process right before the generative call. A request that would
  exceed either window is rejected with `429` + `Retry-After` before any
  network call is made — cheaper and more honest than waiting for the
  provider's own `429` and retrying into a wall that won't move for the
  rest of the day. Deliberately verified with a fake, test-controlled
  clock rather than real waiting or spending real API quota: the
  mechanism being tested is plain Python sliding-window arithmetic, not
  an LLM-behavior claim, so unit tests with an injectable `time_fn` are
  the right tool — unlike RAG, where only a real call could prove the
  model's output actually changed. 8 new tests (6 unit, testing the
  limiter's window/reset/retry-after logic directly; 2 integration,
  proving the route returns 429 without ever calling the mocked LLM, and
  that a batch isolates an item that lands after the limit trips the same
  way a provider failure already does).
- **Correlation IDs** — `correlation.py`, the Python equivalent of the
  ticketing-platform track's `CorrelationIdFilter`: a `contextvars.ContextVar`
  holds the current request's id, and a `logging.Filter` attaches it to
  every log line so `%(correlation_id)s` in the log format is never blank
  mid-request. No explicit cleanup needed the way Java's `finally { MDC.remove() }`
  is — Starlette runs each request in its own asyncio Task, and a
  `ContextVar` set inside one Task is invisible to every other
  concurrently running Task, so there's no shared, reused thread for a
  value to leak across.
- **A real bug, caught live, in the correlation ID work itself** — the
  filter was first attached via `logging.getLogger().addFilter(...)`,
  which looked correct and imported cleanly, but silently never runs:
  `Logger.filter()` is only invoked by the logger that *originates* a
  record, while propagation to an ancestor calls that ancestor's
  *handlers* directly, bypassing the ancestor's own filter. The very
  first `logger.info()` call anywhere else in the codebase would have
  raised `KeyError: 'correlation_id'` inside the logging module the
  moment it ran for real — confirmed by actually triggering one, not by
  reasoning about it in the abstract. Fixed by attaching the filter to
  the handler instead (`handler.addFilter(...)`), which every log record
  passes through regardless of which logger it came from. Pinned down
  with two dedicated regression tests, using an isolated logger tree
  rather than the real root logger — the real one already carries the
  fix by the time the suite has imported `main.py` once, which would
  have silently masked the bug being tested for.
