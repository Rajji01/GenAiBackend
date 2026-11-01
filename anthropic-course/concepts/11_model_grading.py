"""
Lesson 11 — "Model based grading" — GEMINI port.
Pairs with 11_model_grading_claude.py. Explainer: 11_model_grading.md.

Real model grader returning strengths/weaknesses/reasoning/score, integrated into the eval loop.
Gemini clean-JSON via response_mime_type.

Run:
    C:/.../Python313/python.exe anthropic-course/concepts/11_model_grading.py
"""

import json
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


def chat(contents, json_mode=False):
    cfg = types.GenerateContentConfig(
        response_mime_type="application/json" if json_mode else None,
    )
    return client.models.generate_content(model=MODEL, contents=contents, config=cfg).text


FALLBACK = [
    {"task": "Write a Python function that validates an AWS S3 bucket name."},
    {"task": "Write a JSON IAM policy granting read-only access to one S3 bucket."},
    {"task": "Write a regex that matches an AWS access key ID (starts with AKIA)."},
]


def load_dataset():
    p = Path(__file__).with_name("dataset.json")
    return json.loads(p.read_text()) if p.exists() else FALLBACK


def run_prompt(test_case):
    contents = []
    add_user_message(contents, f"Please solve the following task:\n\n{test_case['task']}")
    return chat(contents)


EVAL_PROMPT = """You are an expert code reviewer. Evaluate this AI-generated solution.

Task: {task}
Solution: {solution}

Return a JSON object with:
- "strengths": array of 1-3 key strengths
- "weaknesses": array of 1-3 key areas for improvement
- "reasoning": a concise explanation of your assessment
- "score": a number from 1 to 10"""


def grade_by_model(test_case, output):
    contents = []
    add_user_message(contents, EVAL_PROMPT.format(task=test_case["task"], solution=output))
    return json.loads(chat(contents, json_mode=True))


def run_test_case(test_case):
    output = run_prompt(test_case)
    grade = grade_by_model(test_case, output)
    return {
        "output": output,
        "test_case": test_case,
        "score": grade["score"],
        "reasoning": grade.get("reasoning", ""),
    }


def run_eval(dataset):
    results = [run_test_case(tc) for tc in dataset]
    avg = statistics.mean(r["score"] for r in results)
    print(f"Average score: {avg:.2f}\n")
    return results


if __name__ == "__main__":
    for r in run_eval(load_dataset()):
        print(f"[{r['score']}/10] {r['test_case']['task'][:45]}")
        print(f"       reasoning: {r['reasoning'][:90]}\n")
