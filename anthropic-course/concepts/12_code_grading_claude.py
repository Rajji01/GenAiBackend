"""
Lesson 12 — "Code based grading" — CLAUDE version.
Pairs with 12_code_grading.py (Gemini). Explainer: 12_code_grading.md.

Code graders check deterministic things WITHOUT an API call: Format + Valid Syntax. Here: validate
JSON/Python/Regex by actually trying to parse them (10 if it parses, 0 if it errors). Then COMBINE
the code score with the L11 model score (task-following) → one number.

Dataset needs a "format" field so the grader knows which validator to use.
(L06 callback: course uses prefill "```code" for clean output; we use a "code only" system prompt + stop.)

Run:
    C:/.../Python313/python.exe anthropic-course/concepts/12_code_grading_claude.py
"""

import ast
import json
import re
import statistics
from pathlib import Path
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv(Path(__file__).resolve().parents[2] / "narration-enrichment" / ".env")
client = Anthropic()
MODEL = "claude-haiku-5-5"


def text_of(message):
    return next((b.text for b in message.content if getattr(b, "type", None) == "text"), "")


def add_user_message(messages, text):
    messages.append({"role": "user", "content": text})


def chat(messages, system=None, stop_sequences=None):
    params = {"model": MODEL, "max_tokens": 1000, "messages": messages}
    if system:
        params["system"] = system
    if stop_sequences:
        params["stop_sequences"] = stop_sequences
    return text_of(client.messages.create(**params))


# --- CODE graders: pure Python, no API, deterministic -----------------------
def validate_json(text):
    try:
        json.loads(text.strip())
        return 10
    except json.JSONDecodeError:
        return 0


def validate_python(text):
    try:
        ast.parse(text.strip())
        return 10
    except SyntaxError:
        return 0


def validate_regex(text):
    try:
        re.compile(text.strip())
        return 10
    except re.error:
        return 0


VALIDATORS = {"json": validate_json, "python": validate_python, "regex": validate_regex}


def grade_syntax(output, test_case):
    validator = VALIDATORS.get(test_case.get("format", ""))
    return validator(output) if validator else 0


# --- dataset needs a "format" field ----------------------------------------
FALLBACK = [
    {"task": "Write a Python function that validates an AWS IAM username.", "format": "python"},
    {"task": "Write a JSON IAM policy granting read-only access to one S3 bucket.", "format": "json"},
    {"task": "Write a regex that matches an AWS access key ID (starts with AKIA).", "format": "regex"},
]


def load_dataset():
    p = Path(__file__).with_name("dataset.json")
    return json.loads(p.read_text()) if p.exists() else FALLBACK


def run_prompt(test_case):
    system = "Respond ONLY with raw code in the requested language. No comments, commentary, explanation, or markdown fences."
    messages = []
    add_user_message(messages, f"Task (format: {test_case['format']}):\n{test_case['task']}")
    return chat(messages, system=system, stop_sequences=["```"])


EVAL_PROMPT = """You are an expert code reviewer. Evaluate this solution for how well it follows the task.

Task: {task}
Solution: {solution}

Return a JSON object with: "strengths" (1-3), "weaknesses" (1-3), "reasoning", "score" (1-10)."""


def grade_by_model(test_case, output):
    messages = []
    add_user_message(messages, EVAL_PROMPT.format(task=test_case["task"], solution=output))
    raw = chat(messages, system="Output ONLY a valid JSON object. No fences, no commentary.", stop_sequences=["```"])
    return json.loads(raw.strip())


def run_test_case(test_case):
    output = run_prompt(test_case)
    model_score = grade_by_model(test_case, output)["score"]   # task-following (judgement)
    syntax_score = grade_syntax(output, test_case)             # format + valid syntax (deterministic)
    score = (model_score + syntax_score) / 2                   # combine (tune the weights per use case)
    return {"output": output, "test_case": test_case,
            "model_score": model_score, "syntax_score": syntax_score, "score": score}


def run_eval(dataset):
    results = [run_test_case(tc) for tc in dataset]
    print(f"Average score: {statistics.mean(r['score'] for r in results):.2f}\n")
    return results


if __name__ == "__main__":
    for r in run_eval(load_dataset()):
        print(f"[{r['score']:.1f}/10  model={r['model_score']} syntax={r['syntax_score']}] "
              f"{r['test_case']['format']:6} | {r['test_case']['task'][:40]}")
