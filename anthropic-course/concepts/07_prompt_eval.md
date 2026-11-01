# Lesson 07 — Prompt evaluation

**Anthropic course concept** → Claude ([`07_prompt_eval_claude.py`](07_prompt_eval_claude.py)) +
Gemini ([`07_prompt_eval.py`](07_prompt_eval.py)). Interview Qs: [`../INTERVIEW.md`](../INTERVIEW.md) "Lesson 07".

---

## The concept

Two different things:
- **Prompt engineering** = *how to write* a good prompt (multishot/few-shot examples, XML-tag
  structure, clear instructions, system prompts…).
- **Prompt evaluation** = *measuring how well* a prompt works, with **automated tests** — test
  against expected answers, compare prompt versions, catch errors.

**Three paths after you write a prompt:**
1. Test once, ship → breaks in prod on unexpected inputs. ❌
2. Test a few times + tweak a corner case → better, but users still surprise you. ⚠️
3. **Run it through an eval pipeline → score it → iterate on objective metrics.** ✅ More work, far
   more reliable. **This is evaluation-first.**

Why 1 & 2 are traps: everyone underestimates how weird real user inputs get. Eval catches problems
in *development* instead of after users hit them.

## The mini-pipeline (what the code does = Option 3)
```
golden dataset (input + expected)  →  run the prompt on each  →  grade  →  score X/N
                                   →  tweak the prompt, re-run, compare scores objectively
```
The demo classifies sentiment against 5 labelled cases and prints a pass-rate. Code-graded (exact
match) because the output is a fixed label; open-ended outputs need an **LLM-as-judge** instead.

## Where this lives in my project — this is the CROWN JEWEL 👑

My narration project is a full **Option-3** implementation, not a toy:
- **Golden dataset** — `eval/golden_dataset.json` (17 cases) + `eval/golden_disputes.json` (8, incl.
  a required prompt-injection case). → exactly the "input + expected" above, at scale.
- **`eval/run_eval.py`** — runs the real pipeline, scores per-field.
- **Accuracy vs reliability split** — a timeout/quota failure is a *reliability* finding, not a
  *correctness* one (most tutorials conflate them).
- **Eval-as-a-system** — results persist to `eval_runs` + `eval_results`; `GET /eval/history`
  surfaces per-case pass-rate over time (drift tracking).
- **LLM-as-judge** (P6 `dispute_judge.py`) — grades open-ended proposals on a rubric; the objective
  field is cross-checked by `==` and the judge's opinion overridden on divergence (the judge's judge).
- **Fail-closed threshold gate** — `run_eval_disputes.py` exits non-zero if class-accuracy < 80% or
  grounded-mean < 1.5 → a deploy is *gated* on eval pass-rate. That's Option 3 taken to CI.

So the course taught *why* eval matters; I built the whole pipeline. In an interview, "how do you
know your prompt/LLM app is good?" → walk this. It's the demo-vs-production separator.
