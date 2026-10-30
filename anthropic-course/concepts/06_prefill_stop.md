# Lesson 06 — Prefilling + stop sequences (clean structured output)

**Anthropic course concept** → Claude ([`06_prefill_stop_claude.py`](06_prefill_stop_claude.py)) +
Gemini ([`06_prefill_stop.py`](06_prefill_stop.py)). Interview Qs: [`../INTERVIEW.md`](../INTERVIEW.md) "Lesson 06".

---

## The problem

Claude *likes* to be helpful — ask for JSON and you often get it wrapped in a ```` ```json ```` fence
with a "This rule captures…" sentence after it. Great for humans, **bad for a web app that needs to
copy the raw JSON**. You want the data, nothing else.

## The course's solution: prefill + stop sequence

- **Prefill** the assistant turn with ```` ```json ```` → Claude thinks it already opened a code block
  and just writes the JSON body.
- **Stop sequence** ```` ``` ```` → the moment Claude tries to close the block, generation stops.
- Result: clean JSON, no prose. Then `json.loads(text.strip())`.

Works for anything Claude wraps: code, bullet lists, CSV — prefill with the opener, stop on the closer.

## ⚠️ The divergence (current Claude): prefill is REMOVED

On current Claude models (5.x + the 4.6/4.7/4.8 family) a **last-assistant-turn prefill returns a
400**. So the course's exact trick no longer runs. The modern, first-class replacement is
**structured output**:

| | course trick | modern replacement |
|---|---|---|
| Claude | prefill ```` ```json ```` + stop ```` ``` ```` | **structured outputs** (`output_config.format` / `client.messages.parse()` / Instructor+Pydantic), or a plain "JSON only" system prompt + `stop_sequences` |
| Gemini | — (no assistant prefill) | **`response_mime_type="application/json"`** (+ optional `response_schema`); `stop_sequences` in config |

`stop_sequences` itself still works on Claude — it's only the *prefill* that's gone.

## What the code shows
- **Claude file:** runs the course's prefill (catches the 400 honestly), then a working version =
  "JSON only" system prompt + `stop_sequences`, parsed with `json.loads`.
- **Gemini file:** `json_mode=True` → `response_mime_type="application/json"` → raw JSON directly.

## Where this lives in my project — this is literally why P1 exists

P1 `/enrich` had exactly this problem (Day 2 reproduced it: markdown fence, `"confidence":"High"`,
nested-object). The fix wasn't a prefill hack — it was **Instructor + Pydantic = structured output**:
the response is *forced* into a validated schema via the provider's function-calling, so there's no
fence and no prose to strip, and the shape is guaranteed. **Prefill+stop is the training-wheels
version; structured output (what I shipped) is the production version** — and current Claude
removing prefill pushes everyone toward exactly that.
