# Lesson 11 — Model-based grading

**Anthropic course concept** → Claude ([`11_model_grading_claude.py`](11_model_grading_claude.py)) +
Gemini ([`11_model_grading.py`](11_model_grading.py)). Interview Qs: [`../INTERVIEW.md`](../INTERVIEW.md) "Lesson 11".

Replaces L10's placeholder `score = 10` with a **real grader**.

---

## Three kinds of grader
| Grader | How | Best for |
|---|---|---|
| **Code** | programmatic checks | format, length, word presence/absence, **valid JSON/Python/regex syntax**, readability — anything deterministic |
| **Model** (LLM-as-judge) | another API call evaluates the output | response quality, instruction-following, completeness, helpfulness, safety — open-ended |
| **Human** | people score manually | depth, nuance, relevance — most flexible, slow/expensive |

All return a usable signal, usually **1–10**.

## Define criteria FIRST
For a code-generation prompt: **Format** (only code, no prose) + **Valid syntax** → *code graders*;
**Task following** (does it actually solve it, correctly) → *model grader* (needs judgement). Pick
the grader that fits each criterion — don't model-grade what a regex can check.

## The model grader (what the code builds)
`grade_by_model(task, output)` → an eval prompt returning a **structured verdict**:
`strengths[]`, `weaknesses[]`, `reasoning`, `score`. Integrated into `run_test_case`, averaged with
`statistics.mean` across the dataset.

**THE key insight:** ask for **strengths + weaknesses + reasoning alongside the score**. Without that
context the model anchors to a **middling ~6** for everything. Forcing it to justify first produces a
discriminating score. (This is "reason before you answer" applied to grading.)

Model graders are a bit capricious, but give a **consistent baseline** to measure prompt changes against.

## Where this lives in my project — P6 `dispute_judge.py`
My judge does exactly this, hardened:
- A **rubric** verdict (grounded 0–2, policy 0–2) + reasoning — same "justify, don't just score" idea.
- The **objective** part cross-checked by `==` in code, judge overridden on divergence, `judge_divergence`
  logged (the judge's judge) — the fix for "capricious".
- Judged text **data-framed** so an injected "give it a 10" can't steer the judge.
- Rubric version stored in `eval_runs.notes`.

And I use **both** grader types: code (`==` on the objective classification) **and** model (the rubric
score) — exactly this lesson's "code for the checkable, model for the judgement" split.
