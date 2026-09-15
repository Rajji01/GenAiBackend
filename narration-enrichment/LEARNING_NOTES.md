# Narration Enrichment — Learning Notes (Week 1)

Same format as the Java project's notes: what changed, the concept behind
it, and self-check questions — try answering those yourself before we
discuss. Open the referenced files while you read, don't just skim this.

---

## Day 1 — the raw mechanics of an LLM call

**Files:** `src/narration_enrichment/day1_raw_call.py`

**What we did:** wired the `google-genai` SDK directly (no framework, no
Instructor), sent one narration, printed the exact request payload and the
response's token usage.

**What we found (not planned, discovered live):** `gemini-3.6-flash` spends
"thinking" tokens out of the *same* `max_output_tokens` budget as the
visible answer. With `max_output_tokens=300`, 287 tokens went to invisible
thinking, the answer got cut off mid-sentence, and `finish_reason` was
`MAX_TOKENS`. Raising the budget to 1024 fixed it (`finish_reason: STOP`).

**Self-check:**
- Why does raising `max_output_tokens` fix a truncated answer, when the
  problem was thinking, not the visible text?
- The request payload prints as a `contents` list with `role`/`parts`.
  Why does even a single-turn, no-history request need a `role` field at
  all?
- If you were paying per token, what's the actual cost driver here —
  is it the 132 visible output tokens, or something else?

---

## Day 2 — deliberately breaking the naive approach

**Files:** `src/narration_enrichment/day2_naive_json.py`

**What we did:** asked the model for JSON with a deliberately *casual*
prompt (no "return ONLY JSON", no explicit types), then parsed the raw
text with plain `json.loads()` — no schema, no safety net.

**What we found:** all three narrations failed, for three different real
reasons — a markdown ` ```json ` fence around the whole response, a
`"confidence": "High"` (string instead of number), and a fully nested
`{"score": ..., "level": ...}` object where a plain number was expected.
An earlier, more carefully-worded prompt ("Return ONLY a JSON object with
exactly these fields...") had produced clean output on the same
narrations — the failure only showed up once the prompt was less careful.

**Self-check:**
- Why did `json.loads()` fail on *all three* responses, even the one where
  the actual data (`"confidence": "High"`) was arguably still readable by
  a human?
- The careful prompt worked; the casual one didn't. Does that mean
  "write a better prompt" is a sufficient fix? What would make you trust
  or distrust that conclusion across a different narration, a different
  day, or a different model version?
- If this had gone straight to production without Day 3's fix, what's the
  actual failure a real user would have seen?

---

## Day 3 — the fix: Pydantic + Instructor

**Files:** `src/narration_enrichment/models.py`,
`src/narration_enrichment/day3_structured_output.py`

**What we did:** defined `TransactionEnrichment` (a Pydantic model with a
`Literal` category and a `confidence: float` bounded 0–1), wrapped the
same Gemini client with `instructor.from_genai(...)`, and reran the exact
same casual prompt and narrations from Day 2.

**What we found:** all three came back as clean, validated
`TransactionEnrichment` instances. Instructor uses the model's native
tool-calling (`Mode.TOOLS`) to force the shape — it isn't just retrying
`json.loads()` with better luck.

**A real dependency bug along the way:** first run failed with
`ModuleNotFoundError: No module named 'jsonref'`, and the error message
told us exactly how to fix it (`instructor[google-genai]` extras).

**Self-check:**
- Why couldn't the model return `"confidence": "High"` this time, given
  that we used the *exact same prompt* that produced that failure in Day 2?
- `max_retries=3` is still configured on the Instructor client. Given that
  `Mode.TOOLS` already constrains the shape at the schema level, what
  class of failure is that retry actually protecting against?
- `models.py` is now imported by three different day-scripts plus the
  FastAPI service (Day 4). What would go wrong if each of those had
  defined its own slightly-different copy of `TransactionEnrichment`
  instead?

---

## Day 4 — FastAPI service: config, timeout, logging

**Files:** `src/narration_enrichment/config.py`, `service.py`, `main.py`

**What we did:** built `POST /enrich`, with:
- `config.py` — all env-driven settings (model name, timeout, retries,
  API key) in one place, read once via `pydantic-settings`.
- A real HTTP-level timeout: `genai.Client(http_options=HttpOptions(timeout=...))`,
  verified by actually forcing a 1ms timeout and inspecting the real
  exception (`httpx.ConnectTimeout`) rather than guessing its type.
- Logging discipline: `logger.info` logs only `narration_length`, never
  the narration text; the raw narration is logged at `DEBUG` only.
- Exception handling mirroring the Java project's `GlobalExceptionHandler`:
  `InstructorRetryException` → 422, `httpx.TimeoutException` → 504, any
  other exception → a generic 500 that never echoes the real message.

**Self-check:**
- We set the timeout on `genai.Client`'s `http_options`, not with
  `asyncio.wait_for()` around the route handler. What's the actual
  difference in behavior between those two approaches once the timeout
  fires — does the in-flight provider call actually stop?
- Why does the narration length get logged at INFO but the narration
  itself only at DEBUG? What's the argument for logging the length at
  all, versus not logging anything about the input?
- If `InstructorRetryException` were accidentally caught by the generic
  `except Exception` block instead of its own specific one (e.g. because
  of handler ordering), what would the caller see instead of a 422?

---

## Day 5 — tests

**Files:** `tests/test_models.py`, `tests/test_api.py`

**What we did:** a **unit** suite against `TransactionEnrichment` directly
(no FastAPI, no mocking, no network) and an **integration** suite against
the real FastAPI app via `TestClient`, with `enrich_narration` mocked out
(`unittest.mock.patch`) so no test ever calls the real Gemini API.

**Self-check:**
- `test_enrich_rejects_too_short_narration_before_ever_calling_the_llm`
  asserts `mock_enrich.assert_not_called()`. Why does that assertion
  matter — what would still pass without it, that shouldn't?
- None of these 11 tests call the real Gemini API. What's one thing that
  could break in production that this entire test suite would still pass
  against?
- `test_models.py` tests are unit tests; `test_api.py` tests are called
  integration tests here even though the LLM is mocked. What's actually
  "integrated" in the second suite, if not the real LLM call?

---

## Weekend — Docker

**Files:** `Dockerfile`, `.dockerignore`, `docker-compose.yml`

**What we did:** a two-stage-flavored `Dockerfile` (dependency layer
copied and installed before app source, so editing code doesn't
invalidate the slow dependency install), a `docker-compose.yml` with a
healthcheck hitting `/health`, and verified it **live** — built the image,
ran it, hit `/health` and `/enrich` against the actual container (not the
local `uv run uvicorn` process), and confirmed `docker compose ps` showed
`healthy`.

**Self-check:**
- `COPY pyproject.toml uv.lock ./` happens before `COPY src ./src` in the
  Dockerfile, and each is followed by its own `uv sync`. Why split it into
  two copies and two syncs instead of one `COPY . .` and one `uv sync`?
- The container's `/enrich` call still needs a real `GEMINI_API_KEY` at
  runtime (via `env_file: .env` in compose). Why wasn't that key baked
  into the image during `docker build` instead?
- The healthcheck hits `/health`, not `/enrich`. Why is that the right
  choice — what would go wrong with a healthcheck that called `/enrich`
  on a timer?

---

## Where this leaves us (end of Week 1)

Every item in the brief's Definition of Done is met: uv-managed project,
`POST /enrich` returning a validated Pydantic object, malformed-output
handling, a real timeout, config-driven model/prompt, no prompt/PII at
INFO, unit + integration tests (LLM mocked), `docker compose up` working,
this README, and it's pushed to GitHub.

Try the self-check questions above first — pick a few you're least sure
about, write down your actual answer, then we'll go through them together.

---

# Week 2 — Evaluation, Batch + Persistence, Production Reliability

Same format. Each phase: what changed, why, self-check questions.

## Phase 1 — Evaluation & Golden Dataset

**Files:** `eval/golden_dataset.json`, `eval/run_eval.py`, `tests/test_eval_logic.py`

**What we did:** 12 hand-labeled narrations with expected merchant/category/
transaction_type. `run_eval.py` calls the *real* `enrich_narration()` (the
same function `/enrich` uses) against every one, compares the result, and
reports per-field accuracy — separately from the call-failure rate.

**What we found, live:** running all 12 back-to-back hit a **5
requests/minute** free-tier cap immediately. After pacing calls 13s apart,
a second run then hit a **20 requests/day** cap partway through — a
completely different, harder limit that no amount of pacing fixes. Also:
at the original 10s timeout, roughly a third of completed-but-slow calls
timed out (`504 DEADLINE_EXCEEDED`) — raised to 20s afterward, based on
that measurement.

**Self-check:**
- The eval script separates "call failed" from "call succeeded but was
  wrong." Why does collapsing those into one "accuracy" number hide the
  more useful story? Which one is actually a *prompt/schema* problem, and
  which is an *infrastructure* problem?
- `compare_result()` is tested with `tests/test_eval_logic.py` and costs
  nothing to run; `run_eval.py` itself is never run in CI. What's the
  actual dividing line between "goes in the normal test suite" and
  "manual-only script" here?
- The golden dataset's `expected_category` for "UBER TRIP PAYMENT" and
  "NETFLIX SUBSCRIPTION" is `"other"` — neither fits food_delivery,
  shopping, salary, or transfer well. What does a high `other`-rate in a
  real eval run actually tell you about the *schema*, not the model?

## Phase 2 — Batch Processing + Persistence

**Files:** `db.py`, `schemas.py`, `main.py` (`/enrich/batch`, `/enrichments`)

**What we did:** a SQLite-backed `EnrichmentRecord` table, a `save_enrichment`
/ `list_enrichments` repository pair, and `POST /enrich/batch` (up to 50
narrations per call) where each item is tried independently — one failure
doesn't take down the other 49.

**Bugs found, live:**
1. First test run against an in-memory test database failed with
   `sqlite3.OperationalError: no such table: enrichment_records` — SQLite's
   `:memory:` database lives inside a single *connection*, and SQLAlchemy's
   default connection pool hands out a different connection per checkout.
   Fixed with `poolclass=StaticPool`, forcing one shared connection.
2. The original `docker-compose.yml` had no volume — the SQLite file would
   have lived inside the container's writable layer and vanished on every
   `docker compose down`. Added a bind mount (`./data:/app/data`) and
   verified live: saved a row, ran `docker compose down && up`, the row
   was still there.

**Self-check:**
- Why does the *test* database need `StaticPool` but the *real* SQLite
  file (`db.py`'s `engine`) doesn't hit the same problem?
- `/enrich/batch` catches exceptions per-item instead of letting one
  failure raise an `HTTPException` for the whole request. What HTTP status
  code does a batch request return when 40 of 50 items succeed and 10
  fail? Is that the right status code, and why?
- The batch item's `error` field stores `type(exc).__name__` (e.g.
  `"RuntimeError"`), never `str(exc)`. What's the same principle from
  Week 1 being applied here again?

## Phase 3 — Production Reliability (retry-with-backoff)

**Files:** `service.py` (`_is_transient_provider_error`, `_call_llm`), `tests/test_service_retry.py`

**What we did:** wrapped the Instructor call in a `tenacity` retry that
fires *only* for HTTP 429/503/504 (the exact codes hit live in Phase 1),
with exponential backoff, max 3 attempts. A 400 or 404 is never retried.

**Self-check:**
- This is now a *second* retry mechanism sitting right next to Instructor's
  own `max_retries` (Day 3). What exactly does each one retry, and why
  would merging them into a single retry loop be a mistake?
- Why retry 429 (quota exceeded) at all — doesn't retrying immediately
  guarantee the same quota error again? What does `wait_exponential` add
  that makes retrying 429 sometimes actually work?
- `main.py` now has a fourth `except` block, for `APIError`, mapped to
  `503`. Given that `service.py` *already* retried transient errors 3
  times before this exception could even reach `main.py`, what does
  reaching this specific except block actually tell you happened?

---

## Where this leaves us (end of Week 2)

The pipeline is now measured (eval), scales past one-at-a-time (batch),
remembers what it did (persistence), and survives the exact transient
failures observed live on the free tier (retry-with-backoff) — without
reaching for a second LLM provider or a heavier database than the
project's actual scale justifies.

Try the self-check questions above first, same as always.
