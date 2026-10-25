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

from dotenv import load_dotenv
from anthropic import Anthropic

# Loads ANTHROPIC_API_KEY from narration-enrichment/.env (gitignored — never committed).
load_dotenv()

# Anthropic() auto-reads ANTHROPIC_API_KEY from the environment.
client = Anthropic()
MODEL = "claude-sonnet-4-0"  # the id the course uses; check the `claude-api` skill for latest ids.


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
    print("Answer:", message.content[0].text)
    print("tokens -> input:", message.usage.input_tokens, "| output:", message.usage.output_tokens)


def multi_turn() -> None:
    """A conversation = a list of {role, content}. Claude's roles: 'user' / 'assistant'."""
    messages = [
        {"role": "user", "content": "My name is Rajat."},
        {"role": "assistant", "content": "Nice to meet you, Rajat!"},  # Claude: "assistant" (Gemini: "model")
        {"role": "user", "content": "What's my name?"},
    ]
    message = client.messages.create(model=MODEL, max_tokens=1000, messages=messages)
    print("Multi-turn answer:", message.content[0].text)


if __name__ == "__main__":
    single_turn()
    print("-" * 40)
    multi_turn()
