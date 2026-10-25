# anthropic-course/ — concepts from Anthropic, implemented in free Gemini

**Owner:** Rajat Agrawal · **Started:** 2026-10-25 · **Tutor:** Jarvis

Rajat is taking **Anthropic's course** (Anthropic Academy / Claude courses). The deal set on
2026-10-25:

> "mai anthropic ka course kr rha hu — usme jo sikhaye vo free ka use kr k mje sare concepts
> smjha dio **with implementation** ok jarvis."

So: **Anthropic teaches a concept → Jarvis explains that concept (the *why*, not just the API) and
gives a runnable implementation — but in FREE Gemini, not the paid Anthropic API.** Zero spend; the
concept is provider-agnostic, only the SDK call changes.

> **This track is REACTIVE / trigger-only.** It runs ONLY when Rajat names a specific course
> concept or pastes a module — never proactively, and it is **not** part of the autonomous
> `AGENTS.md` §3-12 self-walk rotation. The self-walk (harden-as-prod + interview-prep) keeps
> running on its own; this folder waits for Rajat's course signal.

---

## The rule (how every lesson works)

1. **Concept source = Anthropic.** Rajat names the concept (or pastes the course module). Jarvis
   does not invent a syllabus — it follows what the course actually teaches.
2. **Implementation = free Gemini.** Every runnable example uses the **`google-genai`** SDK
   (`from google import genai`) + the existing `GEMINI_API_KEY` — the same stack as
   `narration-enrichment/`. Nothing here calls the Anthropic API.
3. **Explain, then implement, then connect.** Each lesson = (a) the concept in plain Hinglish +
   the *why* it matters, (b) a minimal runnable Gemini script, (c) where this already shows up (or
   could) in the narration project — so the course reinforces the real build.
4. **Honesty on Anthropic-specific features.** Some things Anthropic teaches are Claude-specific
   (e.g. prompt caching API, extended thinking, MCP, the exact tool-use block shapes). For those,
   the lesson gives the concept + the **closest Gemini equivalent**, and flags clearly where the
   two differ (that contrast is itself interview-useful). For deep Anthropic-API accuracy, the
   `claude-api` skill is the reference.
5. **Interview-linked.** Each concept also feeds `interview-prep/GENAI.md` when it's interview-
   relevant (don't duplicate — link).

---

## How to run a lesson's code

```bash
# reuse the narration project's env (already has google-genai + GEMINI_API_KEY)
cd narration-enrichment
uv run python ../anthropic-course/concepts/<NN>_<concept>.py
# or standalone: pip install google-genai, export GEMINI_API_KEY=..., python <file>.py
```

Free Gemini models (pick cheap/fast for learning): `gemini-2.5-flash` / `gemini-flash-latest`
(the narration project runs `gemini-3.6-flash`). Each script names its model at top.

---

## Lessons index (grows as the course goes)

| # | Anthropic concept | Gemini implementation | Project tie-in | Status |
|---|---|---|---|---|
| 01 | Making your first request (client, messages, max_tokens, extract) | [`concepts/01_first_request.py`](concepts/01_first_request.py) · [`.md`](concepts/01_first_request.md) | P1 `service.py` core | ✅ 2026-10-25 |

Each lesson ships as: `concepts/<NN>_<concept>.md` (explainer) + `concepts/<NN>_<concept>.py`
(runnable Gemini). Add a row here when a lesson lands.
