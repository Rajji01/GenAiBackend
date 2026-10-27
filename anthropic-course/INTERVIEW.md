# anthropic-course — interview prep (common)

**One file for ALL lessons.** Each lesson adds a small section (2 easy "trace the code" + 1
conceptual). Cross-linked from `interview-prep/GENAI.md`. Answers in `<details>` — try first, then peek.

---

## Lesson 01 — Making your first request

**Q1 (easy).** `max_tokens` — target or limit?
<details><summary>answer</summary>A safety **limit**, not a target. The model writes what it thinks is right and stops; it won't pad to the cap. But if the answer needs more than the cap, it gets cut off mid-sentence.</details>

**Q2 (easy, Claude↔Gemini).** What two things differ when you move the same call from Claude to Gemini?
<details><summary>answer</summary>(1) assistant role is `"assistant"` in Claude, `"model"` in Gemini; (2) text extraction is `message.content[0].text` (Claude, a list of blocks) vs `response.text` (Gemini). Also the call name: `messages.create` vs `models.generate_content`. **Live gotcha:** Claude-5 models think by default, so `content` may start with a `ThinkingBlock` — don't use `content[0]`, pick the first block with `type == "text"`.</details>

**Q3 (conceptual).** How do you get *reliable* structured JSON out of an LLM?
<details><summary>answer</summary>Don't trust prose + `json.loads()`. Force the shape via the provider's native tool/function-calling against a schema (Instructor + Pydantic in my P1), and treat the output as untrusted — validate at the boundary. Retry is a safety net, not the primary defence.</details>

---

## Lesson 02 — Multi-turn conversations

**Q1 (easy).** The API is stateless. What does that force you to do for a multi-turn chat?
<details><summary>answer</summary>Keep the message list yourself and **resend the entire history** on every request — Claude remembers nothing between calls.</details>

**Q2 (easy, trace).** Why append Claude's own reply back into the `messages` list before the next question?
<details><summary>answer</summary>So the follow-up ("write another sentence") has context. The list IS the memory; without the prior assistant turn, the next request is contextless and answers about something random.</details>

**Q3 (conceptual).** What's the hidden cost of resend-everything, and how do real apps handle it?
<details><summary>answer</summary>Token cost grows with conversation length — turn 10 pays for turns 1–9 again. Fix: cap / trim / summarise history. My P3 persists turns in a DB and caps the prompt to the last 6 (`CHAT_MEMORY_MAX_TURNS`).</details>

---

## Lesson 03 — System prompts

**Q1 (easy, trace).** In `chat(messages, system=None)`, why is `system` added to params *conditionally*?
<details><summary>answer</summary>The API rejects `system=None`. Build the params dict and set `params["system"]` only when a non-empty prompt is given. (Gemini: pass `config=None` when there's no `system_instruction`.)</details>

**Q2 (easy).** Why put "you are a patient tutor" in the system slot, not as the first user message?
<details><summary>answer</summary>It's the stable behaviour contract for *every* turn, weighted as higher-priority instruction, and it won't scroll out of a trimmed history like a user turn would. Keeps "who you are" separate from "what the user said."</details>

**Q3 (conceptual).** System prompt vs few-shot vs fine-tuning — when each, and the system prompt's limit?
<details><summary>answer</summary>System prompt = cheapest/instant, first reach (role/tone/format/guardrails). Few-shot = when it's easier to *show* than describe. Fine-tuning = bake large consistent behaviour into weights at scale. Limit: a system prompt is *instruction, not a wall* — prompt injection can try to override it; real defence is structural (my P5: tool results framed "data, not instructions" + whitelist/schema enforced in code).</details>

---

## Lesson 04 — Temperature

**Q1 (easy).** What does temperature actually tune in the generation pipeline?
<details><summary>answer</summary>The **sampling** step. Low (~0) = deterministic, almost always the top-probability token; high (~1) = flattens the distribution for variety. It doesn't change tokenization or the prediction, just how the next token is picked.</details>

**Q2 (easy).** Which temperature for (a) data extraction, (b) brainstorming?
<details><summary>answer</summary>(a) low, 0.0–0.3 (facts/coding/extraction/moderation); (b) high, 0.8–1.0 (brainstorming/creative/marketing). Medium 0.4–0.7 for summarisation/education/constrained-creative.</details>

**Q3 (conceptual).** "Set temperature=0 and you get the same output every time" — true? And what changed on current Claude?
<details><summary>answer</summary>Not guaranteed — temperature changes the *probability* of variety, not a lock; even low temp can differ, and other nondeterminism remains. Current Claude (5.x) **removed** the temperature knob entirely (non-default → 400); adaptive thinking + effort replaced it. Because generation stays nondeterministic, real systems that need one canonical answer use **idempotency keys** (my Hardening H3), not temperature=0.</details>

---

<!-- Next lesson's section goes here. Keep each lesson small: 2 easy + 1 conceptual. -->
