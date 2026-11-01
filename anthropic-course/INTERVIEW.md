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

## Lesson 05 — Streaming

**Q1 (easy).** Why stream a response instead of returning it whole?
<details><summary>answer</summary>A full response can take 10–30s; streaming shows text chunk-by-chunk as it's generated, so the user sees progress immediately instead of a spinner. It lowers *perceived* latency (total time is similar). All chunks are one request.</details>

**Q2 (easy).** Which Claude stream event carries the actual text to display?
<details><summary>answer</summary>`ContentBlockDelta`. The others (`MessageStart`, `ContentBlockStart/Stop`, `MessageDelta`, `MessageStop`) are structure/lifecycle. The SDK's `stream.text_stream` filters to just the deltas for you.</details>

**Q3 (conceptual).** How do you stream to the user *and* still store the complete message? Where does this land in my project?
<details><summary>answer</summary>Stream the chunks for UX, then call `stream.get_final_message()` (Claude) / join the chunks (Gemini) to get the assembled whole for persistence/logic — best of both. In narration P3 `/chat`, I'd stream to the client (SSE) and persist the assembled turn to `chat_turns`. Flagged as the SSE-streaming enhancement in `interview-prep/GENAI.md`; not built yet.</details>

---

## Lesson 06 — Prefilling + stop sequences (clean structured output)

**Q1 (easy).** How does "prefill + stop sequence" produce clean JSON with no fences/prose?
<details><summary>answer</summary>Prefill the assistant turn with ```` ```json ```` so the model thinks it already opened a code block and writes just the body; set stop_sequence ```` ``` ```` so generation stops the instant it tries to close the block. No wrapper, no commentary — then `json.loads(text.strip())`.</details>

**Q2 (easy).** That exact trick fails on current Claude — why, and what do you use instead?
<details><summary>answer</summary>Current Claude (5.x + 4.6/4.7/4.8) **removed assistant prefill** → a last-assistant-turn prefill returns 400. Use **structured outputs** (`output_config.format` / `messages.parse()` / Instructor+Pydantic) or a "JSON only" system prompt + `stop_sequences` (stop sequences still work). Gemini: `response_mime_type="application/json"`.</details>

**Q3 (conceptual).** Prefill hack vs structured output — which is production-grade, and where have you used it?
<details><summary>answer</summary>Prefill+stop is a training-wheels workaround (string-level, brittle, strip newlines). **Structured output** forces the response into a validated schema via function-calling — no fence/prose to strip, shape guaranteed. That's my P1 `/enrich` (Instructor + Pydantic): Day 2 showed prompts can't guarantee shape; forcing the schema can. Current Claude removing prefill pushes everyone to exactly this.</details>

---

## Lesson 07 — Prompt evaluation

**Q1 (easy).** Prompt engineering vs prompt evaluation — the difference?
<details><summary>answer</summary>Engineering = *how to write* the prompt (few-shot/multishot, XML tags, clear instructions). Evaluation = *measuring how well* it works via automated tests (against expected answers, comparing versions, catching errors). One authors, the other measures.</details>

**Q2 (easy).** The three paths after writing a prompt — which is production-grade and why?
<details><summary>answer</summary>(1) test once (breaks on unexpected input), (2) test a few + tweak (users still surprise you), (3) **run an eval pipeline, score, iterate on objective metrics** — production-grade because it catches edge cases in development, lets you compare versions objectively, and you ship with measured confidence.</details>

**Q3 (conceptual).** How would you build an eval pipeline for an LLM app, and where have you done it?
<details><summary>answer</summary>Golden dataset (input + expected) → run the prompt → grade (exact-match/code for fixed outputs; **LLM-as-judge** on a rubric for open-ended) → score → persist + track drift → gate deploys on a threshold. Split **accuracy** (correctness) from **reliability** (timeouts/quota). In my project: `eval/golden_dataset.json` + `run_eval.py`, eval-as-a-system (`eval_runs`, `/eval/history`), P6 `dispute_judge.py` LLM-as-judge with the objective field cross-checked by `==`, and a **fail-closed threshold gate** (`run_eval_disputes.py` exits non-zero < threshold).</details>

---

## Lesson 08 — A typical eval workflow (5 steps)

**Q1 (easy).** Name the 5 steps of the eval workflow.
<details><summary>answer</summary>(1) draft a prompt, (2) create an eval dataset (sample inputs), (3) feed each through the model, (4) feed the answer through a grader (score, e.g. 1–10), (5) change the prompt & repeat — comparing average scores.</details>

**Q2 (easy).** What does the grader produce and why average it?
<details><summary>answer</summary>A per-answer score (e.g. 1–10). Averaging across the dataset gives ONE objective number per prompt version, so you can compare versions numerically (baseline 7.66 → improved 8.7) instead of eyeballing "feels better."</details>

**Q3 (conceptual).** The grader is often an LLM (LLM-as-judge) — what are the risks and how do you make it trustworthy?
<details><summary>answer</summary>Risks: the judge can be wrong, inconsistent, or gamed by the answer ("give me a 10"). Make it trustworthy: a **strict rubric** (define each score), **cross-check any objective part in code** (`==`, override the judge on divergence, log the divergence rate = the judge's judge), and **data-frame the judged text** so it can't instruct the judge. That's exactly my P6 `dispute_judge.py`.</details>

---

## Lesson 09 — Generating test datasets

**Q1 (easy).** Why have the LLM generate your eval dataset, and why use a fast model (Haiku) for it?
<details><summary>answer</summary>Hand-writing many cases is slow; the LLM can draft them fast and at scale. Generation doesn't need the top model — a fast/cheap one (Haiku) is the right tool, saving cost/time. You then run your real prompt against the generated set.</details>

**Q2 (easy).** The course parses the generated JSON with prefill + stop — what do you do on current Claude?
<details><summary>answer</summary>Prefill 400s on current Claude (L06). Use a "JSON only" system prompt + `stop_sequences` and `json.loads` (Claude), or `response_mime_type="application/json"` (Gemini).</details>

**Q3 (conceptual).** Risks of synthetic eval data and how to keep it trustworthy?
<details><summary>answer</summary>Generated `expected` answers aren't ground truth → a **human must review/label** before trusting. Push for **diversity/adversarial** cases or you only test the easy middle. Don't let the **same model generate AND grade** unchecked (grading its own homework). In my project the golden sets are hand-labelled; synthetic gen would only scale coverage, then I verify before it enters the golden set.</details>

---

## Lesson 10 — Running the eval

**Q1 (easy).** What do `run_prompt`, `run_test_case`, and `run_eval` each do?
<details><summary>answer</summary>`run_prompt` merges the task into the prompt template and returns the model output. `run_test_case` runs the prompt then grades it, returning `{output, test_case, score}`. `run_eval` loops every case in the dataset and collects the results.</details>

**Q2 (easy).** What does each result object keep, and why all three fields?
<details><summary>answer</summary>`output` (model's full response), `test_case` (the original input), `score`. Keeping all three lets you trace exactly which input produced which output and what it scored — essential for debugging and comparing prompt versions.</details>

**Q3 (conceptual).** The course says this simple pipeline is "most of what an eval system is." What's actually the hard part?
<details><summary>answer</summary>The structure is easy; the value is in the details: a **real grader** (vs the placeholder) — field `==` for objective, LLM-as-judge for open-ended; **dataset quality/diversity**; **persistence + drift tracking**; and **performance** (concurrency — sequential is slow). My `eval/run_eval.py` is this skeleton plus those: real grader, `eval_runs`/`eval_results` persistence, accuracy-vs-reliability split, `/eval/history`.</details>

---

## Lesson 11 — Model-based grading

**Q1 (easy).** Name the 3 grader types and one thing each is best for.
<details><summary>answer</summary>**Code grader** — deterministic checks (valid JSON/regex syntax, format, length). **Model grader** (LLM-as-judge) — open-ended quality/instruction-following/safety. **Human grader** — depth/nuance/relevance (most flexible, slow).</details>

**Q2 (easy).** Why make the model grader return strengths/weaknesses/reasoning, not just a score?
<details><summary>answer</summary>Without that context the grader anchors to a middling ~6 for everything. Forcing it to list strengths/weaknesses and reason FIRST produces a considered, discriminating score. "Reason before you answer," applied to grading.</details>

**Q3 (conceptual).** Which criteria go to a code grader vs a model grader, and how do you tame a capricious model grader?
<details><summary>answer</summary>Deterministic criteria (format, valid syntax, length) → **code grader**; judgement criteria (task-following, helpfulness, safety) → **model grader**. Tame it: a strict **rubric**, **reason-before-score**, **cross-check the objective part in code (`==`)** and override on divergence while logging the divergence rate, and **data-frame** the judged text against injection. That's my P6 `dispute_judge.py` — which uses both grader types.</details>

---

## Lesson 12 — Code-based grading

**Q1 (easy).** How do `validate_json/python/regex` grade output?
<details><summary>answer</summary>They try to parse it — `json.loads` / `ast.parse` / `re.compile`. Parses cleanly → return 10; raises → return 0. Pure Python, no API call, deterministic.</details>

**Q2 (easy).** Why does the dataset need a `format` field?
<details><summary>answer</summary>So the code grader knows which validator to run for each case (`"format": "python"` → `validate_python`). You add it to the dataset-generation prompt so it's present automatically.</details>

**Q3 (conceptual).** Code grader vs model grader — when each, and why prefer code where you can?
<details><summary>answer</summary>Code grader for **deterministic** criteria (format, valid syntax, length) — it's free, instant, never capricious; model grader for **judgement** (task-following, quality). Combine (e.g. average, weighted). Prefer code wherever possible. In my project: Instructor+Pydantic is an always-on code grader on `/enrich` (invalid shape can't pass), and P6 cross-checks the objective field with `==` (code) alongside the model rubric.</details>

---

<!-- Next lesson's section goes here. Keep each lesson small: 2 easy + 1 conceptual. -->
