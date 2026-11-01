# Lesson 12 — Code-based grading

**Anthropic course concept** → Claude ([`12_code_grading_claude.py`](12_code_grading_claude.py)) +
Gemini ([`12_code_grading.py`](12_code_grading.py)). Interview Qs: [`../INTERVIEW.md`](../INTERVIEW.md) "Lesson 12".

Completes the grader picture from L11: now **code grader + model grader together**.

---

## The idea
Some things don't need an LLM to judge — they're deterministic. A **code grader** checks:
- **Format** — did it return only the code type asked for (no prose)?
- **Valid syntax** — does the output actually parse as JSON / Python / regex?

"Task following" still needs the **model grader** (judgement). Code handles the checkable;
model handles the judgement. Combine both.

## The syntax validators (pure Python, no API — free + instant)
```python
def validate_json(t):   #  json.loads  -> 10 / 0
def validate_python(t): #  ast.parse   -> 10 / 0
def validate_regex(t):  #  re.compile  -> 10 / 0
```
Parses → 10; raises → 0. **No tokens spent.** That's the beauty of code graders: cheap,
deterministic, repeatable.

## Dataset needs a `format` field
`{"task": "...", "format": "python"}` — so the grader knows which validator to run. Add `format`
to your dataset-generation prompt (L09) so it's there automatically.

## Combine the scores
```python
score = (model_score + syntax_score) / 2
```
Equal weight here; **tune the weights** to what matters (e.g. weight syntax higher if invalid code is
a hard fail). Prompt clarity also matters — tell the model "respond only with code, no commentary"
(course also prefills ```` ```code ````; on current Claude use the system-prompt + stop route — L06).

## The point
The absolute score isn't "good" or "bad" — what matters is whether you can **raise it by refining
the prompt**. Now you have a quantitative dial for prompt-engineering progress.

## Where this lives in my project
- **Code grader** ↔ P1's whole premise: Instructor + Pydantic **validates structure at runtime** —
  that's an always-on code grader on every `/enrich` (invalid shape can't pass). P6 cross-checks the
  objective classification with `==` (code grader) next to the model rubric (model grader).
- **Combine** ↔ P6 uses both signals; my eval separates **accuracy** (code-checkable) from
  **reliability**, the same "deterministic vs judgement" split this lesson draws.

Prefer a code grader wherever the check is deterministic — it's free, instant, and never capricious.
