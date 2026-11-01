# Lesson 10 — Running the eval

**Anthropic course concept** → Claude ([`10_run_eval_claude.py`](10_run_eval_claude.py)) +
Gemini ([`10_run_eval.py`](10_run_eval.py)). Interview Qs: [`../INTERVIEW.md`](../INTERVIEW.md) "Lesson 10".

The eval arc assembled: L07 why → L08 loop → L09 dataset → **L10 the running pipeline**.

---

## The pipeline — three functions

| Function | Responsibility |
|---|---|
| `run_prompt(test_case)` | merge the task into the prompt template, call the model, return the output |
| `run_test_case(test_case)` | call `run_prompt`, then **grade** → return `{output, test_case, score}` |
| `run_eval(dataset)` | loop every case, collect all results into a list |

Load `dataset.json` (from L09), run, inspect the structured results. Each result keeps the **output**,
the **original test_case**, and the **score** — so you can see exactly what produced what.

**The grade is a PLACEHOLDER (`score = 10`) for now** — the real grader is the next lesson. The
point of this lesson is the *pipeline shape*, proven end-to-end with a stub score.

Note: the prompt here is deliberately bare ("Please solve the following task: …"), so the model
returns **verbose** output (no format instructions). That's the kind of weakness the eval will later
expose and you'll fix by iterating the prompt (L08's step 5).

Expect ~30s even on Haiku for a few cases (it's sequential — optimization/concurrency comes later).

## Where this lives in my project — this IS `run_eval.py`'s shape
`eval/run_eval.py` is exactly this skeleton, productionised:
- `run_prompt` ↔ calling the real `/enrich` or dispute pipeline per case,
- `run_test_case` ↔ run + **real grader** (field `==` for objective, LLM-as-judge for open-ended),
- `run_eval` ↔ the loop, plus **persistence** to `eval_runs`/`eval_results` and the **accuracy vs
  reliability** split, surfaced via `/eval/history`.

The course says it well: *this simple pipeline is the majority of what an eval system is* — the hard
part is the details (good prompts, a real grader, persistence, concurrency). My project has those details.
