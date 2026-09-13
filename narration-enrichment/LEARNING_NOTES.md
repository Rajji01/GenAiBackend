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

## Where this leaves us

Every item in the brief's Definition of Done is met: uv-managed project,
`POST /enrich` returning a validated Pydantic object, malformed-output
handling, a real timeout, config-driven model/prompt, no prompt/PII at
INFO, unit + integration tests (LLM mocked), `docker compose up` working,
this README, and it's pushed to GitHub.

Try the self-check questions above first — pick a few you're least sure
about, write down your actual answer, then we'll go through them together.
