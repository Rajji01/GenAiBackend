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

---

# Week 3, Day 1 — a live run catches a bug 30 passing tests missed

**Files:** `service.py` (`_is_transient_provider_error`), `main.py`, `tests/test_service_retry.py`, `tests/test_api.py`

**What happened:** the daily quota reset overnight, so the first thing
done was re-run `eval/run_eval.py` for a clean baseline. It worked
(11/12 completed, 100% accuracy) — but the one failure's *exact error
string* didn't match what Phase 3's retry-with-backoff was written to
detect.

**The bug:** `_is_transient_provider_error` checked `isinstance(exc, APIError)`.
That's never what `_client.create()` actually raises. Instructor's own
internal retry loop catches *every* exception from the underlying call —
including ones it never actually shape-retried — and re-raises it as
`InstructorRetryException(...) from original_error`. So the real
`APIError` was always sitting one level down, in `exc.__cause__` — and
the retry-with-backoff built in Week 2, Phase 3, had **never once fired**,
in any real request, since the day it was written.

**Why the tests didn't catch it:** `test_service_retry.py` mocked
`_client.create` to raise a *raw* `APIError` directly — which is a
perfectly reasonable-looking mock, and 9/9 tests passed against it. It
just didn't match what `.create()` actually raises in real life. The
tests were internally consistent and completely wrong about the world
outside them.

**The fix:** check both the exception itself and its `__cause__`. Rewrote
the tests to raise the *actual* wrapped shape (confirmed live, by mocking
one level deeper — `_raw_client.models.generate_content`, the real
boundary Instructor itself wraps — and reading what came out).

**A second, related bug this exposed in `main.py`:** the exhausted-retry
case (a real 503 that survived 3 backoff attempts and still failed) was
landing in the *same* `except InstructorRetryException` branch as a
genuine shape/validation failure — both raise the same exception type —
and was being reported to the caller as `422 "Could not extract structured
data"` instead of `503 "provider unavailable"`. Fixed by inspecting
`exc.__cause__` inside that one `except` block.

**Self-check:**
- Why does mocking `_client.create` directly produce a *different*
  exception shape than mocking `_raw_client.models.generate_content`
  (the layer underneath it)? What is `_client.create` actually doing
  between those two points?
- This bug shipped, passed code review (such as it was), passed 9 unit
  tests, and sat untriggered through every request in Week 2 — because
  the failure mode it was meant to handle is inherently rare (transient
  provider errors) and nothing ever exercised it for real until this
  morning's eval run. What's the general lesson about testing failure
  paths that don't happen often, versus ones that happen on every
  request?
- The fix adds a second `isinstance` check on `exc.__cause__`. What
  happens to this detection logic if a future version of Instructor
  changes how it wraps exceptions — does anything here re-break silently,
  or does it fail loudly?

---

# Week 3, RAG — making the model consistent with its own past decisions

**Files:** `rag.py` (new), `db.py`, `service.py`, `main.py`, `tests/test_rag.py` (new), `tests/test_api.py`

**The problem this addresses:** Phase 1's eval already showed the model
can classify the same *kind* of merchant differently on different calls,
and has no way to know about local/unusual merchants it wasn't trained
on. Nothing forces it to agree with an earlier decision about basically
the same narration.

**The design decision made before writing any code:** don't reach for a
vector database. This project already persists every enrichment
(Phase 2, `db.py`). That table already *is* a knowledge base — it just
needed a vector on each row and a similarity search. Adding a dedicated
vector DB for a few hundred/thousand rows would be infrastructure the
project doesn't need yet, not correctness.

**How it works end to end:**
1. A new narration arrives. Before calling the LLM, it's embedded
   (`task_type="RETRIEVAL_QUERY"`) and compared by cosine similarity
   against every past row that has a stored embedding.
2. Matches above a similarity floor (0.70), capped to the top 3, get
   formatted into a short "here's how similar past narrations were
   classified" block and folded into the prompt.
3. After the LLM responds, the *new* narration is embedded again — this
   time with `task_type="RETRIEVAL_DOCUMENT"` — and that vector is stored
   alongside the row, so it becomes a candidate for future lookups.

**The `task_type` asymmetry is not cosmetic.** Gemini's embedding model
optimizes a "this is a document to be found later" vector differently
from "this is a query searching for something" — using the same
task_type for both silently produces worse similarity scores, with no
error to warn you. Confirmed by reading the actual API docs rather than
assuming both calls could just use the same default.

**Cold start, handled honestly:** an empty table (or a genuinely novel
narration with nothing similar enough) returns no examples, and
`build_context_block` returns `None` — the prompt falls back to exactly
the plain Week 1 version. There's no attempt to force in irrelevant
examples just because the feature exists.

**Graceful degradation, proven, not assumed:** both embedding calls
(retrieval and storage) are wrapped in their own try/except in
`_enrich_and_persist`. A test (`test_enrich_degrades_gracefully_when_embedding_call_fails`)
mocks `embed_text` to raise, and confirms `/enrich` still returns 200
with `context=None` — RAG is an enhancement layered on top of a working
system, not a new point of failure for it.

**Live proof, not just unit tests — and reported honestly both ways:**
- First attempt: seeded a fictional local vendor ("Chaiwala Express") as
  `food_delivery`, then sent a new, similar narration with and without
  the RAG context. Both came back identical — the model already got it
  right without help. This was reported as a genuine null result, not
  quietly dropped for a better-looking example.
- Second attempt, deliberately chosen from a case Phase 1's eval had
  already gotten wrong: seeded a past `"UBER TRIP PAYMENT"` row with
  `category="transfer"` (simulating a human correction), then sent a
  fresh, near-identical Uber narration. **Without** RAG context it
  classified as `"other"` (matching the original Phase 1 finding).
  **With** RAG context retrieving the seeded row, it classified as
  `"transfer"` — a clean, real demonstration that the model's output
  changed because of retrieved history, not because anything about the
  model itself changed.

**A loose end noticed, not yet chased down:** the Uber query actually
retrieved *two* seeded rows above the similarity floor (Uber and
Chaiwala), not just the Uber one — both cleared 0.70 even though they're
unrelated merchants. At 256 dimensions and this few real data points,
the similarity floor may be looser than it looks; worth revisiting once
there's enough real usage to tune `MIN_SIMILARITY` on data instead of by
eye.

**Self-check:**
- Why does `build_context_block` return `None` instead of an empty
  string for the no-examples case, and why does `service.py` check
  `if context` rather than `if context is not None` when deciding whether
  to inject the block into the prompt?
- `rag.py` duplicates `_is_transient_provider_error`'s logic as its own
  private `_is_transient`, instead of importing it from `service.py`.
  Given the two retry policies currently behave identically, what's the
  actual argument for the duplication rather than just importing it?
- The embedding column is stored as a JSON-encoded string on the same
  row, decoded and compared in a Python loop for every request. At what
  rough scale (rows, or requests/sec) would this genuinely stop being
  "fine for now" and become a real bottleneck — and what would you reach
  for first when it does?
- Both live tests seeded the "similar past narration" by hand before
  calling `/enrich`. What would have to be different about this feature
  for it to produce a genuinely useful example on someone's *very first*
  real narration, with no seeding at all?

---

Try the self-check questions above first, same as always.
