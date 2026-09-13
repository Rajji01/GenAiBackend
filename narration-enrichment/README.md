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

11 tests, no network calls, no API key required — the LLM is mocked out
for every test that goes through the HTTP layer.

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
- **PII/prompt content logged at DEBUG only, metadata at INFO** — a bank
  narration can carry account fragments or names. Verified live: the
  running server's INFO logs contain `narration_length=51`, never the
  narration text itself.
- **Exceptions mapped by type, not by string-matching messages** —
  `InstructorRetryException` → 422, `httpx.TimeoutException` → 504,
  anything else → a generic 500 that never echoes the real exception
  message back to the caller. The same principle as the Java project's
  `GlobalExceptionHandler`, in a different language.

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
