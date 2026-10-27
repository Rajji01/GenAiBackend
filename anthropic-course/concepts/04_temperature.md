# Lesson 04 — Temperature

**Anthropic course concept** → Gemini ([`04_temperature.py`](04_temperature.py), the live demo)
+ Claude ([`04_temperature_claude.py`](04_temperature_claude.py), shows the honest divergence).
Interview Qs: [`../INTERVIEW.md`](../INTERVIEW.md) "Lesson 04".

---

## The concept

Text generation = **tokenize → predict (probabilities for the next token) → sample (pick one)**.
**Temperature** tunes that last step:

- **Low (≈0)** → deterministic: almost always picks the highest-probability token.
- **High (≈1)** → flattens the distribution: more varied / creative output.

It's the same "controlled randomness" from the LLM-internals card (`interview-prep/GENAI.md`), now as
a dial. Picking the right range per task:

| Range | Use for |
|---|---|
| **0.0–0.3** low | facts, coding, data extraction, moderation |
| **0.4–0.7** medium | summarisation, education, problem-solving, constrained creative |
| **0.8–1.0** high | brainstorming, creative writing, marketing, jokes |

**Key nuance (interview):** temperature changes the *probability* of variety — it does **not
guarantee** different outputs. Even at high temp you can get the same answer twice.

## The big Claude ↔ Gemini divergence (live-verified)

| | Claude (current, 5.x) | Gemini |
|---|---|---|
| temperature knob | **removed** — a non-default `temperature` returns **HTTP 400** | present, `config=GenerateContentConfig(temperature=…)`, range 0.0–2.0 |
| how you control style instead | adaptive thinking (always on) + `output_config.effort` + prompt | temperature (and top_p/top_k) |

So the course's `chat(messages, temperature=…)` runs **as taught on Gemini**, but on current Claude
it 400s. This isn't a bug in the course — it's model evolution: Anthropic replaced the fixed
temperature/top_p sampling controls with adaptive thinking + effort on the 5.x family (and the
`2026-10-21` API version rejects `temperature` on every model). The `_claude.py` file demonstrates
the 400 honestly rather than pretending it works.

> To actually *see* temperature, run `04_temperature.py` (Gemini) twice at 0.0 (near-identical) and
> twice at 1.0 (varied).

## Where this lives in my project

- The **LLM-internals card** (`interview-prep/GENAI.md`) already explained sampling + temperature.
- **P1 `/enrich`** wants deterministic JSON → that's a *low-temperature* need. On Gemini I'd set a low
  temperature; on current Claude I'd lean on structured output + low effort instead.
- The deeper bridge: because generation is **non-deterministic by construction**, I built
  **idempotency keys (Hardening H3)** so a retried `/enrich` replays ONE canonical stored answer
  instead of re-rolling the dice. Temperature is the knob; idempotency is the defence.
