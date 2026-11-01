"""
Lesson 12 — "Code based grading" — GEMINI port.
Pairs with 12_code_grading_claude.py. Explainer: 12_code_grading.md.

Deterministic code graders (JSON/Python/Regex syntax) combined with the model grader.

Run:
    C:/.../Python313/python.exe anthropic-course/concepts/12_code_grading.py
"""

import ast
import json
import re
import statistics
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv(Path(__file__).resolve().parents[2] / "narration-enrichment" / ".env")
client = genai.Client()
MODEL = "gemini-2.5-flash"


def add_user_message(contents, text):
    contents.append({"role": "user", "parts": [{"text": text}]})


def chat(contents, system=None, json_mode=False, stop_sequences=None):
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json" if json_mode else None,
        stop_sequences=stop_sequences,
    )
    return client.models.generate_content(model=MODEL, contents=contents, config=cfg).text


# --- CODE graders: pure Python, no API --------------------------------------
def validate_json(text):
    try:
        json.loads(text.strip()); return 10
    except json.JSONDecodeError:
        return 0


def validate_python(text):
    try:
        ast.parse(text.strip()); return 10
    except SyntaxError:
        return 0


def validate_regex(text):
    try:
        re.compile(text.strip()); return 10
    except re.error:
        return 0


VALIDATORS = {"json": validate_json, "python": validate_python, "regex": validate_regex}


def grade_syntax(output, test_case):
    validator = VALIDATORS.get(test_case.get("format", ""))
    return validator(output) if validator else 0


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
    contents = []
    add_user_message(contents, f"Task (format: {test_case['format']}):\n{test_case['task']}")
    return chat(contents, system=system, stop_sequences=["```"])


EVAL_PROMPT = """You are an expert code reviewer. Evaluate this solution for how well it follows the task.

Task: {task}
Solution: {solution}

Return a JSON object with: "strengths" (1-3), "weaknesses" (1-3), "reasoning", "score" (1-10)."""


def grade_by_model(test_case, output):
    contents = []
    add_user_message(contents, EVAL_PROMPT.format(task=test_case["task"], solution=output))
    return json.loads(chat(contents, json_mode=True))


def run_test_case(test_case):
    output = run_prompt(test_case)
    model_score = grade_by_model(test_case, output)["score"]
    syntax_score = grade_syntax(output, test_case)
    score = (model_score + syntax_score) / 2
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
