# Lesson 09 — Generating test datasets

**Anthropic course concept** → Claude ([`09_generate_dataset_claude.py`](09_generate_dataset_claude.py)) +
Gemini ([`09_generate_dataset.py`](09_generate_dataset.py)). Interview Qs: [`../INTERVIEW.md`](../INTERVIEW.md) "Lesson 09".

Continues the eval arc (L07 why → L08 loop → **L09 where the dataset comes from**).

---

## The concept

An eval needs a dataset of inputs. You can hand-write it — or have the **LLM generate it**. For a
prompt that writes AWS Python / JSON / Regex, you ask the model for an array of `{"task": "..."}`
objects, then save to `dataset.json` to load during evaluation.

**Use a fast, cheap model to generate** (the course uses Haiku): data generation doesn't need the
top model, and you'll make many cases. Then run your *real* prompt (possibly a stronger model)
against this generated set.

Flow: `generate_dataset()` → parse JSON → `dataset.json` → feed into the L08 eval loop.

## L06 callback (the divergence bites again)
The course parses the generated JSON with **assistant prefill** (`add_assistant_message("```json")`)
+ a stop sequence. That **400s on current Claude** (prefill removed — see L06). So here:
- **Claude:** "Output ONLY a valid JSON array" system prompt + `stop_sequences` → `json.loads`.
- **Gemini:** `response_mime_type="application/json"` → clean JSON directly.

The course's `chat()` here also passes `temperature=1.0` and reads `content[0].text` — both diverge on
current Claude (L04 temperature removed; L02 thinking-block). Our versions already handle all three.

## Caveats (interview-worthy — don't skip)
Synthetic data is great for **coverage + speed**, but:
- The generated `expected` answers aren't ground truth — **a human must review/label** before trusting them.
- Push for **diversity** (edge cases, adversarial inputs), or you only test the easy middle.
- Don't let the *same* model both generate cases AND grade them unchecked — that's a closed loop
  grading its own homework.

## Where this fits in my project
My `eval/golden_dataset.json` (17) + `golden_disputes.json` (8) are **hand-labelled** — highest
trust. Synthetic generation (this lesson) is how I'd **scale coverage** cheaply, e.g. auto-propose
new narration/policy cases with Haiku, then hand-verify the expected labels before they enter the
golden set. Required injection case in `golden_disputes.json` = the "push for adversarial diversity"
rule in action.
