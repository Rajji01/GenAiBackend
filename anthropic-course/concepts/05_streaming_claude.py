"""
Lesson 05 — "Streaming" — CLAUDE (native Anthropic API) version.
Pairs with 05_streaming.py (Gemini port). Explainer: 05_streaming.md.

Why: a full response can take 10–30s. Streaming sends the text in chunks as it's generated, so the
user sees it build word-by-word instead of staring at a spinner.

Run:
    C:/.../Python313/python.exe anthropic-course/concepts/05_streaming_claude.py
"""

from pathlib import Path
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv(Path(__file__).resolve().parents[2] / "narration-enrichment" / ".env")
client = Anthropic()
MODEL = "claude-haiku-5-5"


def add_user_message(messages, text):  # course helper — reuse, don't inline
    messages.append({"role": "user", "content": text})


if __name__ == "__main__":
    messages = []
    add_user_message(messages, "Write a 1-sentence description of a fake database.")

    # --- Raw events (what the course shows first) --------------------------
    # Every event is part of ONE request: MessageStart -> ContentBlockStart ->
    # ContentBlockDelta (the actual text) -> ContentBlockStop -> MessageDelta -> MessageStop.
    #   stream = client.messages.create(model=MODEL, max_tokens=1000, messages=messages, stream=True)
    #   for event in stream:
    #       print(event.type)

    # --- Simplified text streaming (what you usually want) -----------------
    # The SDK's context manager filters to just the text deltas:
    with client.messages.stream(model=MODEL, max_tokens=1000, messages=messages) as stream:
        for text in stream.text_stream:          # each chunk as it arrives
            print(text, end="", flush=True)      # flush so it appears live, not buffered
        print()
        final = stream.get_final_message()       # the assembled whole, for storage/further logic

    print("[stop_reason]", final.stop_reason)    # best-of-both: live chunks + a complete object
