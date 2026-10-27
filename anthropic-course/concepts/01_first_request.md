# Lesson 01 — Making your first request

**Anthropic course concept** → implemented in **BOTH** Claude (native) and free Gemini (the port).
Runnable: [`01_first_request_claude.py`](01_first_request_claude.py) · [`01_first_request.py`](01_first_request.py) (Gemini). Run both, compare line-for-line — the mapping table below is exactly that diff.

---

## The concept (5 building blocks)

Making a first LLM API request is always the same 5 steps, whatever the provider:

1. **Secure the key.** Put it in a `.env` file, load it with `python-dotenv`, and add `.env` to
   `.gitignore`. The key never sits in code and never gets committed. *(Leak a key = someone spends
   your quota.)*
2. **Create a client.** One object that knows your key + talks to the provider.
3. **Call the create function** with three things: **model** (which brain), **max_tokens** (a
   safety cap on length), **messages** (the conversation so far).
4. **Understand messages.** A conversation is a list of `{role, content}` dicts. `role` is either
   the human (**user**) or the model (**assistant**). You send the history; the model appends the
   next turn.
5. **Extract the text** from the response object (it also carries metadata like token usage).

**The `max_tokens` nuance (interview-worthy):** it's a *safety limit, not a target*. If you set
1000, the model writes what it thinks is right and stops — it does **not** pad to reach 1000. But if
the answer *needs* more than the cap, it gets **cut off** mid-sentence. So: cap high enough to not
truncate, low enough to bound cost/runaways.

---

## Anthropic ↔ Gemini — the exact mapping

Same concept, only the call changes. This table is the whole lesson:

| Step | Anthropic (the course) | Free Gemini (what we run) |
|---|---|---|
| Install | `pip install anthropic python-dotenv` | `pip install google-genai python-dotenv` |
| Key env var | `ANTHROPIC_API_KEY` | `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) |
| Import + client | `from anthropic import Anthropic`<br>`client = Anthropic()` | `from google import genai`<br>`client = genai.Client()` |
| Model id | `"claude-sonnet-4-0"` | `"gemini-2.5-flash"` |
| The call | `client.messages.create(model, max_tokens, messages)` | `client.models.generate_content(model, contents, config)` |
| Length cap | `max_tokens=1000` (required) | `config=GenerateContentConfig(max_output_tokens=1000)` (optional) |
| A message | `{"role": "user", "content": "hi"}` | `{"role": "user", "parts": [{"text": "hi"}]}` |
| Assistant role | `"assistant"` | **`"model"`** ← the gotcha |
| Get the text | `message.content[0].text` | `response.text` |
| Token usage | `message.usage` | `response.usage_metadata` |

**Three things that bite beginners moving Anthropic → Gemini:**
1. assistant role is spelled **`model`** in Gemini;
2. text lives under **`parts`**, not `content`;
3. `response.text` is a shortcut — under the hood Gemini also returns a list of candidates/parts
   (like Anthropic's `content` block list), `response.text` just grabs the text for you.

**Claude-5 gotcha (hit live):** Haiku/Sonnet/Opus 5 think by default, so `message.content` can
**start with a `ThinkingBlock`** — `content[0].text` then raises `AttributeError`. Grab the first
block whose `type == "text"` instead (the `text_of()` helper in the Claude scripts). Gemini's
`response.text` already does this for you.

**Gemini-specific gotcha (from the narration project):** some Gemini models spend **"thinking"
tokens out of the same `max_output_tokens` budget** as the visible answer — so a *too-low* cap can
silently truncate the real answer because thinking ate the budget. (Narration `README.md`, Day 1.)

---

## Where this already lives in my project

This lesson IS the foundation of **P1** in `narration-enrichment/`:
- `service.py` creates exactly this client (`genai.Client(...)`) and calls `generate_content`.
- The narration build wraps it with **Instructor** so the response comes back as a validated
  Pydantic object instead of raw `response.text` — that's Lesson "structured output" building on
  top of this one. But strip Instructor away and the beating heart is this 5-step request.

So: Anthropic taught the request; I already shipped it (in Gemini) as P1's core. ✅
