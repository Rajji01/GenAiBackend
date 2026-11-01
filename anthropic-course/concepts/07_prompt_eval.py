"""
Lesson 07 — "Prompt evaluation" — GEMINI port.
Pairs with 07_prompt_eval_claude.py. Explainer: 07_prompt_eval.md.

Same "Option 3" mini-pipeline: golden dataset -> run the prompt -> grade -> score.

Run:
    C:/.../Python313/python.exe anthropic-course/concepts/07_prompt_eval.py
"""

from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv(Path(__file__).resolve().parents[2] / "narration-enrichment" / ".env")
client = genai.Client()
MODEL = "gemini-2.5-flash"


def add_user_message(contents, text):
    contents.append({"role": "user", "parts": [{"text": text}]})


def chat(contents, system=None):
    cfg = types.GenerateContentConfig(system_instruction=system)
    return client.models.generate_content(model=MODEL, contents=contents, config=cfg).text


SYSTEM = "Classify the sentiment. Respond with EXACTLY one word: positive, negative, or neutral. No other text."

CASES = [
    {"text": "This product is amazing, I love it!", "expected": "positive"},
    {"text": "Worst purchase ever, totally broke on day one.", "expected": "negative"},
    {"text": "It arrived on Tuesday.", "expected": "neutral"},
    {"text": "meh, it's fine I guess", "expected": "neutral"},
    {"text": "Absolutely fantastic, exceeded expectations!", "expected": "positive"},
]


def classify(text):
    contents = []
    add_user_message(contents, text)
    return chat(contents, system=SYSTEM).strip().lower().rstrip(".")


def run_eval():
    passed = 0
    for c in CASES:
        got = classify(c["text"])
        ok = got == c["expected"]
        passed += ok
        print(f"[{'PASS' if ok else 'FAIL'}] expected={c['expected']:<8} got={got:<12} | {c['text'][:42]}")
    print(f"\nScore: {passed}/{len(CASES)} = {passed / len(CASES):.0%}")


if __name__ == "__main__":
    run_eval()
