"""
Lesson 05 — "Streaming" — GEMINI port.
Pairs with 05_streaming_claude.py. Explainer: 05_streaming.md.

Same idea: see text appear chunk-by-chunk instead of waiting for the whole response.
Gemini uses a dedicated streaming call that YIELDS chunks; each chunk's `.text` is the delta.

Run:
    C:/.../Python313/python.exe anthropic-course/concepts/05_streaming.py
"""

from pathlib import Path
from dotenv import load_dotenv
from google import genai

load_dotenv(Path(__file__).resolve().parents[2] / "narration-enrichment" / ".env")
client = genai.Client()
MODEL = "gemini-2.5-flash"


def add_user_message(contents, text):  # course helper — reuse, don't inline
    contents.append({"role": "user", "parts": [{"text": text}]})


if __name__ == "__main__":
    contents = []
    add_user_message(contents, "Write a 1-sentence description of a fake database.")

    chunks = []
    # Gemini: generate_content_stream yields response chunks as they're produced.
    for chunk in client.models.generate_content_stream(model=MODEL, contents=contents):
        print(chunk.text, end="", flush=True)    # the delta, live
        chunks.append(chunk.text or "")
    print()

    full_text = "".join(chunks)                  # assemble the whole for storage/further logic
    print("[chars]", len(full_text))
