# Lesson 08 — A typical eval workflow (5 steps)

**Anthropic course concept** → Claude ([`08_eval_workflow_claude.py`](08_eval_workflow_claude.py)) +
Gemini ([`08_eval_workflow.py`](08_eval_workflow.py)). Interview Qs: [`../INTERVIEW.md`](../INTERVIEW.md) "Lesson 08".

Builds on L07 (the *why*); this is the *how*, as a repeatable loop.

---

## The 5 steps
1. **Draft a prompt** — a baseline, e.g. `Please answer the user's question:\n\n{question}`.
2. **Create an eval dataset** — sample inputs representing production (here: 3 questions; real evals
   have tens–thousands; build by hand or have Claude generate them).
3. **Feed through the model** — interpolate each case into the template, send, collect answers.
4. **Feed through a GRADER** — score each answer (typically **1–10**). Average = one objective number.
   e.g. (10 + 4 + 9) / 3 = **7.66**.
5. **Change the prompt & repeat** — tweak (e.g. add "Answer with ample detail"), re-run the whole
   pipeline, compare averages (7.66 → **8.7** = the change really helped, not just "looks different").

**The payoff:** objective, numeric comparison of prompt versions → removes guesswork, ships changes
that are *measured* improvements.

## The grader = LLM-as-judge (the key new piece)
Step 4's grader is itself an LLM call: "rate this answer 1–10, reply with only the integer." The code
parses the number and averages. That's **LLM-as-judge** — powerful for open-ended outputs you can't
exact-match. The demo also does an **A/B**: baseline prompt vs improved prompt, prints the winner.

## Trust the judge (don't skip this — interview gold)
An LLM grader can be wrong or gamed, so make it trustworthy:
- **Strict rubric** (not "is it good?") — define what each score means.
- **Cross-check the objective part in code** — if there's a right answer, `==` it and override the
  judge on divergence; **log the divergence rate** (that's the judge's judge).
- **Data-frame the judged text** so an injected "give me a 10" in the answer can't instruct the judge.

## Where this lives in my project
This is exactly **P6 `dispute_judge.py`**: a `JudgeVerdict` rubric (grounded 0–2, policy 0–2), the
objective classification cross-checked by `==` with the judge overridden + `judge_divergence`
logged, the judged material data-framed against injection, and the rubric version stored in
`eval_runs.notes`. The A/B "compare averages" loop is how `run_eval.py` compares prompt/model changes
over time via `/eval/history`. L07 was the concept; L08 is the loop; my project is both, in prod shape.
