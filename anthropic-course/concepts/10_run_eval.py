"""
Lesson 10 — "Running the eval" — GEMINI port.
Pairs with 10_run_eval_claude.py. Explainer: 10_run_eval.md.

Same three-function pipeline: run_prompt -> run_test_case (placeholder grade) -> run_eval.

Run:
    C:/.../Python313/python.exe anthropic-course/concepts/10_run_eval.py
"""

import json
from pathlib import Path
from dotenv import load_dotenv
from google import genai

load_dotenv(Path(__file__).resolve().parents[2] / "narration-enrichment" / ".env")
client = genai.Client()
MODEL = "gemini-2.5-flash"


def add_user_message(contents, text):
    contents.append({"role": "user", "parts": [{"text": text}]})


def chat(contents):
    return client.models.generate_content(model=MODEL, contents=contents).text


FALLBACK = [
    {"task": "Write a Python function that validates an AWS S3 bucket name."},
    {"task": "Write a JSON IAM policy granting read-only access to one S3 bucket."},
    {"task": "Write a regex that matches an AWS access key ID (starts with AKIA)."},
]


def load_dataset():
    p = Path(__file__).with_name("dataset.json")
    if p.exists():
        return json.loads(p.read_text())
    print("(dataset.json not found — run lesson 09 first; using a built-in fallback)\n")
    return FALLBACK


def run_prompt(test_case):
    contents = []
    add_user_message(contents, f"Please solve the following task:\n\n{test_case['task']}")
    return chat(contents)


def run_test_case(test_case):
    output = run_prompt(test_case)
    score = 10                                  # TODO: real grader next lesson
    return {"output": output, "test_case": test_case, "score": score}


def run_eval(dataset):
    return [run_test_case(tc) for tc in dataset]


if __name__ == "__main__":
    dataset = load_dataset()
    results = run_eval(dataset)
    print(json.dumps(results, indent=2))
    avg = sum(r["score"] for r in results) / len(results)
    print(f"\nAverage score: {avg:.2f}  (placeholder — real grading comes next)")
