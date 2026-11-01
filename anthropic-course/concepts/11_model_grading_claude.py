"""
Lesson 11 — "Model based grading" — CLAUDE version.
Pairs with 11_model_grading.py (Gemini). Explainer: 11_model_grading.md.

Replaces L10's placeholder score with a REAL model grader (LLM-as-judge). The grader returns a
structured verdict: strengths / weaknesses / reasoning / score (1-10).

KEY INSIGHT: ask for strengths+weaknesses+reasoning ALONGSIDE the score — without that context,
graders default to middling ~6.
(L06 callback: course parses via prefill "```json" + stop → 400 on current Claude; we use JSON-only
system prompt + stop instead.)

Run:
    C:/.../Python313/python.exe anthropic-course/concepts/11_model_grading_claude.py
"""

import json
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


FALLBACK = [
    {"task": "Write a Python function that validates an AWS S3 bucket name."},
    {"task": "Write a JSON IAM policy granting read-only access to one S3 bucket."},
    {"task": "Write a regex that matches an AWS access key ID (starts with AKIA)."},
]


def load_dataset():
    p = Path(__file__).with_name("dataset.json")
    return json.loads(p.read_text()) if p.exists() else FALLBACK


def run_prompt(test_case):
    messages = []
    add_user_message(messages, f"Please solve the following task:\n\n{test_case['task']}")
    return chat(messages)


EVAL_PROMPT = """You are an expert code reviewer. Evaluate this AI-generated solution.

Task: {task}
Solution: {solution}

Return a JSON object with:
- "strengths": array of 1-3 key strengths
- "weaknesses": array of 1-3 key areas for improvement
- "reasoning": a concise explanation of your assessment
- "score": a number from 1 to 10"""


def grade_by_model(test_case, output):
    """Model grader (LLM-as-judge). Strengths/weaknesses/reasoning force a considered score."""
    messages = []
    add_user_message(messages, EVAL_PROMPT.format(task=test_case["task"], solution=output))
    raw = chat(
        messages,
        system="Output ONLY a valid JSON object. No markdown fences, no commentary.",
        stop_sequences=["```"],
    )
    return json.loads(raw.strip())


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
