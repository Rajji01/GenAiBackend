"""
Lesson 02 — "Multi-turn conversations" — CLAUDE (native Anthropic API) version.
Pairs with 02_multi_turn.py (the Gemini port). Explainer: 02_multi_turn.md.

KEY IDEA: the Claude API is STATELESS. Claude remembers nothing between requests.
To have a conversation, YOU keep the message list and resend the whole history every time.

Run:
    cd narration-enrichment
    uv run python ../anthropic-course/concepts/02_multi_turn_claude.py
"""

from pathlib import Path
from dotenv import load_dotenv
from anthropic import Anthropic

# key from narration-enrichment/.env (gitignored), CWD-independent
load_dotenv(Path(__file__).resolve().parents[2] / "narration-enrichment" / ".env")
client = Anthropic()
MODEL = "claude-haiku-5-5"  # cheapest current model; "claude-sonnet-4-0" is retired/unavailable


def text_of(message):
    """Claude-5 models think first: content can START with a ThinkingBlock, so content[0].text
    (what the course assumed) can crash. Pick the first block whose type is 'text'."""
    return next((b.text for b in message.content if getattr(b, "type", None) == "text"), "")


# --- the three helpers the course teaches ---------------------------------
def add_user_message(messages, text):
    messages.append({"role": "user", "content": text})


def add_assistant_message(messages, text):
    messages.append({"role": "assistant", "content": text})


def chat(messages):
    """ONE stateless request: send the ENTIRE history, get the next reply's text."""
    message = client.messages.create(model=MODEL, max_tokens=1000, messages=messages)
    return text_of(message)


if __name__ == "__main__":
    # The flow that actually works: keep appending, resend everything.
    messages = []

    add_user_message(messages, "Define quantum computing in one sentence")
    answer = chat(messages)
    print("A1:", answer)

    add_assistant_message(messages, answer)       # <-- feed Claude's own reply back in
    add_user_message(messages, "Write another sentence")
    final_answer = chat(messages)                 # now "another sentence" HAS context
    print("A2:", final_answer)

    # Proof of statelessness: a FRESH list with only the follow-up has no context,
    # so Claude answers about something random.
    stateless = []
    add_user_message(stateless, "Write another sentence")
    print("No-history A2:", chat(stateless))
