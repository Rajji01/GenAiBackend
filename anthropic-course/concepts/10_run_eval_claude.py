"""
Lesson 10 — "Running the eval" — CLAUDE version.
Pairs with 10_run_eval.py (Gemini). Explainer: 10_run_eval.md.

The core pipeline, three functions:
  run_prompt(test_case)   -> merge task into the prompt, call the model, return output
  run_test_case(test_case)-> run_prompt + GRADE (placeholder score=10 for now; real grader next lesson)
  run_eval(dataset)       -> loop every case, collect {output, test_case, score}
Loads dataset.json (from lesson 09); falls back to a built-in set so it runs standalone.

Run:
    C:/.../Python313/python.exe anthropic-course/concepts/10_run_eval_claude.py
"""

import json
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


def chat(messages, system=None):
    params = {"model": MODEL, "max_tokens": 1000, "messages": messages}
    if system:
        params["system"] = system
    return text_of(client.messages.create(**params))


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
    """Merge the prompt template with the test case, return the model output."""
    prompt = f"Please solve the following task:\n\n{test_case['task']}"
    messages = []
    add_user_message(messages, prompt)
    return chat(messages)                       # deliberately bare prompt → verbose output (fix later)


def run_test_case(test_case):
    """Run the prompt, then grade. Grade is a PLACEHOLDER until the grader lesson."""
    output = run_prompt(test_case)
    score = 10                                  # TODO: real grader next lesson
    return {"output": output, "test_case": test_case, "score": score}


def run_eval(dataset):
    """Run every case, collect the results."""
    return [run_test_case(tc) for tc in dataset]


if __name__ == "__main__":
    dataset = load_dataset()
    results = run_eval(dataset)                  # ~30s even on Haiku for a few cases
    print(json.dumps(results, indent=2))
    avg = sum(r["score"] for r in results) / len(results)
    print(f"\nAverage score: {avg:.2f}  (placeholder — real grading comes next)")
