"""
Lesson 03 — "System prompts" — GEMINI port.
Pairs with 03_system_prompts_claude.py. Explainer: 03_system_prompts.md.

Same idea as Claude; the KEY difference: Gemini carries the system prompt as
`system_instruction` INSIDE a GenerateContentConfig, not as a top-level `system=` param.

Run:
    C:/.../Python313/python.exe anthropic-course/concepts/03_system_prompts.py
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
    """Gemini: the system prompt rides in config.system_instruction (only when given)."""
    config = types.GenerateContentConfig(system_instruction=system) if system else None
    resp = client.models.generate_content(model=MODEL, contents=contents, config=config)
    return resp.text


TUTOR = """
You are a patient math tutor.
Do not directly answer a student's questions.
Guide them to a solution step by step, with hints.
"""


if __name__ == "__main__":
    q = "How do I solve 5x + 2 = 3 for x?"

    m1 = []
    add_user_message(m1, q)
    print("=== no system ===\n", chat(m1))

    m2 = []
    add_user_message(m2, q)
    print("\n=== math-tutor system ===\n", chat(m2, system=TUTOR))
