"""
Lesson 01 — "Making your first request" — CLAUDE (native Anthropic API) version.
Pairs with 01_first_request.py (the free-Gemini port). Explainer: 01_first_request.md.

This is the course's own code, verbatim-in-spirit. Compare it line-for-line with the Gemini file.

Run:
    cd narration-enrichment          # has .env with ANTHROPIC_API_KEY (gitignored)
    uv add anthropic                 # one-time, if not already added
    uv run python ../anthropic-course/concepts/01_first_request_claude.py
Standalone: pip install anthropic python-dotenv ; set ANTHROPIC_API_KEY in the env.
"""

from pathlib import Path
from dotenv import load_dotenv
from anthropic import Anthropic

# Load ANTHROPIC_API_KEY from narration-enrichment/.env (gitignored), no matter which folder you run from.
load_dotenv(Path(__file__).resolve().parents[2] / "narration-enrichment" / ".env")

# Anthropic() auto-reads ANTHROPIC_API_KEY from the environment.
client = Anthropic()
MODEL = "claude-haiku-5-5"  # cheapest current model ($0.10/$0.50 per 1M) — great for learning.
# (The course printed "claude-sonnet-4-0", which is retired/unavailable on this key. Swap to
#  "claude-sonnet-5-5" or "claude-opus-5-5" anytime for more capability.)


def text_of(message):
    """Claude-5 models think first: content can START with a ThinkingBlock, so content[0].text
    (what the course assumed) can crash. Pick the first block whose type is 'text'."""
    return next((b.text for b in message.content if getattr(b, "type", None) == "text"), "")


def single_turn() -> None:
    """The lesson's core example: one user message in, one answer out."""
    message = client.messages.create(
        model=MODEL,
        max_tokens=1000,  # SAFETY cap on length, NOT a target (Claude stops when it's done).
        messages=[
            {"role": "user", "content": "What is quantum computing? Answer in one sentence"},
        ],
    )
    # `content` is a LIST of blocks; the first block's `.text` is the answer.
    print("Answer:", text_of(message))
    print("tokens -> input:", message.usage.input_tokens, "| output:", message.usage.output_tokens)


def multi_turn() -> None:
    """A conversation = a list of {role, content}. Claude's roles: 'user' / 'assistant'."""
    messages = [
        {"role": "user", "content": "My name is Rajat."},
        {"role": "assistant", "content": "Nice to meet you, Rajat!"},  # Claude: "assistant" (Gemini: "model")
        {"role": "user", "content": "What's my name?"},
    ]
    message = client.messages.create(model=MODEL, max_tokens=1000, messages=messages)
    print("Multi-turn answer:", text_of(message))


if __name__ == "__main__":
    single_turn()
    print("-" * 40)
    # multi_turn()
