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
5. **Interview-linked.** Feed interview-relevant concepts into `interview-prep/GENAI.md` (link,
   don't duplicate).

---

## How to run a lesson's code

```bash
cd narration-enrichment          # has .env with BOTH keys + the uv env
uv add anthropic                 # one-time, if not already in the project
uv run python ../anthropic-course/concepts/<NN>_<concept>_claude.py   # Claude version
uv run python ../anthropic-course/concepts/<NN>_<concept>_gemini.py   # Gemini version
# standalone: pip install anthropic google-genai python-dotenv ; set the two keys in env
```

Model ids (check latest via the `claude-api` skill): Claude e.g. `claude-sonnet-4-0`; Gemini free
e.g. `gemini-2.5-flash` / `gemini-flash-latest`.

---

## Lessons index (grows as the course goes)

| # | Anthropic concept | Claude impl | Gemini impl | Project tie-in | Status |
|---|---|---|---|---|---|
| 01 | Making your first request (client, messages, max_tokens, extract) | [`01_first_request_claude.py`](concepts/01_first_request_claude.py) | [`01_first_request.py`](concepts/01_first_request.py) · [explainer](concepts/01_first_request.md) | P1 `service.py` core | ✅ 2026-10-25 |

Each lesson ships as: `concepts/<NN>_<concept>.md` (explainer) + `_claude.py` + `_gemini.py`
(the Gemini file for lesson 01 is named `01_first_request.py` for back-compat). Add a row when a
lesson lands.
