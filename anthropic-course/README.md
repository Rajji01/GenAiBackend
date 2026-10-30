# anthropic-course/ — concepts from Anthropic, implemented in BOTH Claude & Gemini

**Owner:** Rajat Agrawal · **Started:** 2026-10-25 · **Tutor:** Jarvis

Rajat is taking **Anthropic's course** (Anthropic Academy / Claude courses). The deal:

> "mai anthropic ka course kr rha hu — usme jo sikhaye vo mje sare concepts smjha dio **with
> implementation** ok jarvis." → then (2026-10-25): "**ab gemini or claude dono use krenge**
> anthropic course k lie… **dono se padhenge ache se.**"

So: **Anthropic teaches a concept → Jarvis explains it (the *why*, deeply, Hinglish) and gives
runnable implementations in BOTH Claude (the native API the course teaches) AND free Gemini (the
port).** Seeing the same concept two ways is itself the lesson — the concept is provider-agnostic,
only the SDK call changes.

> **This track is REACTIVE / trigger-only.** It runs ONLY when Rajat names a specific course
> concept or pastes a module — never proactively, and it is **not** part of the autonomous
> `AGENTS.md` §3-12 self-walk rotation. The self-walk (harden-as-prod + interview-prep) keeps
> running on its own; this folder waits for Rajat's course signal.

---

## The rule (how every lesson works)

1. **Concept source = Anthropic.** Rajat names the concept (or pastes the course module). Jarvis
   does not invent a syllabus — it follows what the course actually teaches.
2. **Implementation = BOTH Claude and Gemini.** Each lesson ships two runnable scripts:
   - **Claude** — `anthropic` SDK (`from anthropic import Anthropic`) + `ANTHROPIC_API_KEY`. This is
     the course's native path.
   - **Gemini** — `google-genai` SDK (`from google import genai`) + `GEMINI_API_KEY`. The free port.
   - **Both keys live in `narration-enrichment/.env` — GITIGNORED, NEVER commit.** (The Anthropic
     key was pasted in chat 2026-10-25; Rajat said use it as-is.)
3. **Explain, then implement (both), then connect.** Each lesson = (a) the concept + the *why*,
   (b) the Claude script **and** the Gemini script, side-by-side mapping, (c) where it shows up (or
   could) in the narration project — so the course reinforces the real build.
4. **Anthropic-specific features** (prompt caching, extended thinking, MCP, exact tool-use block
   shapes): show the **real Claude** version + the **closest Gemini equivalent**, and flag where
   they differ (that contrast is interview-useful). Use the `claude-api` skill for Anthropic-API
   accuracy (model ids, params).
5. **Interview-linked — ONE common file.** Each lesson adds a small section (2 easy "trace" + 1
   conceptual) to the single [`INTERVIEW.md`](INTERVIEW.md) in this folder — **not** per-lesson
   interview files. Also cross-link it from `interview-prep/GENAI.md` (link, don't duplicate).
6. **Reuse the course's helper methods.** Once a helper is introduced (Lesson 02:
   `add_user_message` / `add_assistant_message`, `chat()`), reuse it in every later lesson — don't
   inline raw message dicts. (Rajat's correction, 2026-10-27.) Claude-5 extraction uses a
   `text_of()` helper (first `type=="text"` block), not `content[0].text`.

---

## How to run a lesson's code

Each script loads the API keys from `narration-enrichment/.env` **automatically** (via an absolute
path), so you can run it from **any folder** — VS Code's run button works too.

**Option A — plain Python (VS Code / system interpreter).** Install the deps once into *that*
interpreter, then run any lesson:
```bash
# one-time (use the SAME python VS Code runs with):
python -m pip install -r anthropic-course/requirements.txt
# then run a lesson directly:
python anthropic-course/concepts/02_multi_turn_claude.py
```
> If VS Code shows `ModuleNotFoundError: No module named 'dotenv'`, the deps went into a *different*
> Python than the one running the file. Install with the exact interpreter VS Code uses, e.g.
> `C:/Users/prern/AppData/Local/Programs/Python/Python313/python.exe -m pip install -r anthropic-course/requirements.txt`.

**Option B — the narration uv env:**
```bash
cd narration-enrichment && uv add anthropic
uv run python ../anthropic-course/concepts/02_multi_turn_claude.py
```

Model ids (check latest via the `claude-api` skill): Claude e.g. `claude-sonnet-4-0`; Gemini free
e.g. `gemini-2.5-flash` / `gemini-flash-latest`.

---

## Lessons index (grows as the course goes)

| # | Anthropic concept | Claude impl | Gemini impl | Project tie-in | Status |
|---|---|---|---|---|---|
| 01 | Making your first request (client, messages, max_tokens, extract) | [`01_first_request_claude.py`](concepts/01_first_request_claude.py) | [`01_first_request.py`](concepts/01_first_request.py) · [explainer](concepts/01_first_request.md) | P1 `service.py` core | ✅ 2026-10-25 |
| 02 | Multi-turn conversations (stateless API, maintain history, 3 helpers) | [`02_multi_turn_claude.py`](concepts/02_multi_turn_claude.py) | [`02_multi_turn.py`](concepts/02_multi_turn.py) · [explainer](concepts/02_multi_turn.md) | P3 chat (`chat_sessions`/`chat_turns` + memory-cap N=6) | ✅ 2026-10-27 |
| 03 | System prompts (role/tone; math-tutor; flexible `chat(system=None)`) | [`03_system_prompts_claude.py`](concepts/03_system_prompts_claude.py) | [`03_system_prompts.py`](concepts/03_system_prompts.py) · [explainer](concepts/03_system_prompts.md) | P1/P3/P5/P6 prompt layers | ✅ 2026-10-27 |
| 04 | Temperature (sampling dial; **Claude-5 removed it → 400**, Gemini keeps it) | [`04_temperature_claude.py`](concepts/04_temperature_claude.py) (honest 400) | [`04_temperature.py`](concepts/04_temperature.py) (live demo) · [explainer](concepts/04_temperature.md) | LLM-internals card; P1 low-temp; H3 idempotency | ✅ 2026-10-27 |
| 05 | Streaming (chunk-by-chunk; events; `text_stream` + `get_final_message`) | [`05_streaming_claude.py`](concepts/05_streaming_claude.py) | [`05_streaming.py`](concepts/05_streaming.py) · [explainer](concepts/05_streaming.md) | P3 `/chat` SSE (GENAI backlog) | ✅ 2026-10-28 |
| 06 | Prefill + stop → clean JSON (**Claude removed prefill → 400**; use structured output) | [`06_prefill_stop_claude.py`](concepts/06_prefill_stop_claude.py) | [`06_prefill_stop.py`](concepts/06_prefill_stop.py) (JSON mode) · [explainer](concepts/06_prefill_stop.md) | **P1 Instructor+Pydantic** (the production version) | ✅ 2026-10-30 |

Interview Qs for all lessons: **[`INTERVIEW.md`](INTERVIEW.md)** (one common file).
Issues hit while running lessons (what broke · why · fix): **[`JOURNAL.md`](JOURNAL.md)** (one common file).
Practice tasks — **you build, Jarvis verifies**: **[`PRACTICE.md`](PRACTICE.md)**. **Section 1 (Lessons 01–06) ✅ complete** — 7 practice tasks + capstone.

Each lesson ships as: `concepts/<NN>_<concept>.md` (explainer) + `_claude.py` + `_gemini.py`
(the Gemini file for lesson 01 is named `01_first_request.py` for back-compat) **+ a section in the
common [`INTERVIEW.md`](INTERVIEW.md)**. Add a row when a lesson lands.
