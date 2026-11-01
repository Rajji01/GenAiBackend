"""
Lesson 07 — "Prompt evaluation" — CLAUDE version.
Pairs with 07_prompt_eval.py (Gemini). Explainer: 07_prompt_eval.md.

Prompt ENGINEERING = how to write a good prompt. Prompt EVALUATION = MEASURING how well it works,
with automated tests. This file is "Option 3" in miniature: a dataset -> run the prompt -> grade ->
score. (Code-graded here; real systems add an LLM-as-judge for open-ended outputs — see your P6.)

Run:
    C:/.../Python313/python.exe anthropic-course/concepts/07_prompt_eval_claude.py
"""

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


# --- the prompt under test -------------------------------------------------
SYSTEM = "Classify the sentiment. Respond with EXACTLY one word: positive, negative, or neutral. No other text."

# --- the golden dataset (input + expected) ---------------------------------
CASES = [
    {"text": "This product is amazing, I love it!", "expected": "positive"},
    {"text": "Worst purchase ever, totally broke on day one.", "expected": "negative"},
    {"text": "It arrived on Tuesday.", "expected": "neutral"},
    {"text": "meh, it's fine I guess", "expected": "neutral"},
    {"text": "Absolutely fantastic, exceeded expectations!", "expected": "positive"},
]


def classify(text):
    messages = []
    add_user_message(messages, text)
    return chat(messages, system=SYSTEM).strip().lower().rstrip(".")


def run_eval():
    passed = 0
    for c in CASES:
        got = classify(c["text"])
        ok = got == c["expected"]
        passed += ok
        print(f"[{'PASS' if ok else 'FAIL'}] expected={c['expected']:<8} got={got:<12} | {c['text'][:42]}")
    print(f"\nScore: {passed}/{len(CASES)} = {passed / len(CASES):.0%}")
    # Option 3: now you'd tweak SYSTEM and re-run, comparing scores OBJECTIVELY.


if __name__ == "__main__":
    run_eval()
