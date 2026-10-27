"""
Lesson 03 — "System prompts" — CLAUDE (native Anthropic API) version.
Pairs with 03_system_prompts.py (Gemini port). Explainer: 03_system_prompts.md.

A system prompt shapes Claude's ROLE / tone / behaviour. It is passed SEPARATELY from the
conversation (the `system=` param), not as a user message.

Run:
    C:/.../Python313/python.exe anthropic-course/concepts/03_system_prompts_claude.py
"""

from pathlib import Path
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv(Path(__file__).resolve().parents[2] / "narration-enrichment" / ".env")
client = Anthropic()
MODEL = "claude-haiku-5-5"  # cheapest current model; "claude-sonnet-4-0" is retired/unavailable


def text_of(message):
    """Claude-5 models think first: content can START with a ThinkingBlock, so content[0].text
    (what the course assumed) can crash. Pick the first block whose type is 'text'."""
    return next((b.text for b in message.content if getattr(b, "type", None) == "text"), "")


def add_user_message(messages, text):
    messages.append({"role": "user", "content": text})


def chat(messages, system=None):
    """Flexible chat: include `system` ONLY when given — the API rejects system=None."""
    params = {"model": MODEL, "max_tokens": 1000, "messages": messages}
    if system:
        params["system"] = system          # <-- conditional: the key detail
    message = client.messages.create(**params)
    return text_of(message)


TUTOR = """
You are a patient math tutor.
Do not directly answer a student's questions.
Guide them to a solution step by step, with hints.
"""


if __name__ == "__main__":
    q = "How do I solve 5x + 2 = 3 for x?"

    # WITHOUT a system prompt: Claude just solves it outright.
    m1 = []
    add_user_message(m1, q)
    print("=== no system ===\n", chat(m1))

    # WITH the tutor system prompt: Claude guides with hints instead of answering.
    m2 = []
    add_user_message(m2, q)
    print("\n=== math-tutor system ===\n", chat(m2, system=TUTOR))
