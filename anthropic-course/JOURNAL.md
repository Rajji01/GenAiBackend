# anthropic-course — JOURNAL (issues · why · fix)

**One file for every issue hit while running the lessons.** Newest on top. Format: what broke →
why it broke → how it was fixed. Companion to [`INTERVIEW.md`](INTERVIEW.md) (Qs) and the lessons.

---

## 2026-10-30 — Lesson 06

### 6. Assistant **prefill removed** on current Claude (last-assistant-turn prefill → 400)
- **Where:** L06 `06_prefill_stop_claude.py`, the course's `add_assistant_message(messages, "```json")`.
- **Why:** current Claude models (5.x + 4.6/4.7/4.8) dropped assistant message prefilling; a
  last-assistant-turn prefill returns a **400**. (Sibling of the L04 temperature removal.)
  Exact server message (live, haiku-5-5): *"This model does not support assistant message prefill.
  The conversation must end with a user message."*
- **Fix:** not a bug — expected divergence, caught + explained. Use the modern path: **structured
  outputs** (`output_config.format` / Instructor+Pydantic) or a "JSON only" system prompt +
  `stop_sequences` (stop sequences still work). Gemini: `response_mime_type="application/json"`.

## 2026-10-27 — Lessons 01–04 setup & run

### 5. `TypeError: Messages.create() got an unexpected keyword argument 'temperature'`
- **Where:** L04 `04_temperature_claude.py`, on the explicit `temperature=0.0` call.
- **Why:** current Claude models (5.x) **removed the temperature knob** — on the installed SDK the
  parameter no longer exists on `messages.create()`, so it's a **client-side `TypeError`** (older
  SDKs that still send it get a server **400**). Anthropic replaced temperature/top_p with adaptive
  thinking + `output_config.effort`.
- **Fix:** not a bug — expected divergence, handled with try/except that prints the explanation. The
  real low-vs-high creativity demo runs on Gemini (`04_temperature.py`), which keeps the knob.

### 4. `AttributeError: 'ThinkingBlock' object has no attribute 'text'`
- **Where:** L02 `02_multi_turn_claude.py`, the 3rd (no-history) call.
- **Why:** Claude-5 models **think by default**, so the response `content` list can **start with a
  `ThinkingBlock`**; the course's `content[0].text` assumed index 0 is always text.
- **Fix:** `text_of(message)` helper = first block whose `type == "text"`. Applied to every Claude
  lesson (01/02/03/04).

### 3. `anthropic.NotFoundError: 404 - model: claude-sonnet-4-0`
- **Where:** all Claude lessons (the model the course printed).
- **Why:** `claude-sonnet-4-0` is retired / not available on this API key.
- **Fix:** switched to **`claude-haiku-5-5`** (cheapest current, $0.10/$0.50 per 1M). Definitive
  check for any key: `client.models.list()`.

### 2. API key not found — `.env` not loaded (latent; caught before it bit)
- **Where:** would hit any lesson run from a folder other than `narration-enrichment/`.
- **Why:** `load_dotenv()` searches the **current working directory**; lessons run from
  `anthropic-course/`, but the key lives in `narration-enrichment/.env`.
- **Fix:** load via an **absolute path** — `load_dotenv(Path(__file__).resolve().parents[2] /
  "narration-enrichment" / ".env")` — so it works from any CWD / the VS Code run button.

### 1. `ModuleNotFoundError: No module named 'dotenv'`
- **Where:** running any lesson in VS Code.
- **Why:** the deps weren't installed in the **interpreter VS Code actually runs** (system
  Python313); the `pip install` either hadn't run or landed in a different Python.
- **Fix:** install with the **exact** interpreter that runs the file —
  `C:/Users/prern/AppData/Local/Programs/Python/Python313/python.exe -m pip install anthropic
  google-genai python-dotenv` — and added [`requirements.txt`](requirements.txt). Rule: install +
  run with the same `python.exe`.

---

<!-- New issues go at the TOP of the current date's section (or a new date section). -->
