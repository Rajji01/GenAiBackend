"""
Lesson 06 — "Prefilling + stop sequences" (clean structured output) — GEMINI port.
Pairs with 06_prefill_stop_claude.py. Explainer: 06_prefill_stop.md.

Gemini doesn't do assistant-prefill the same way; its FIRST-CLASS clean-JSON path is
`response_mime_type="application/json"` (optionally + a response_schema). That's the modern
equivalent of the prefill hack: structured output, no markdown fences, no prose. Stop sequences
also exist (`stop_sequences` in the config).

Run:
    C:/.../Python313/python.exe anthropic-course/concepts/06_prefill_stop.py
"""

import json
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv(Path(__file__).resolve().parents[2] / "narration-enrichment" / ".env")
client = genai.Client()
MODEL = "gemini-2.5-flash"


def add_user_message(contents, text):
    contents.append({"role": "user", "parts": [{"text": text}]})


def chat(contents, system=None, json_mode=False, stop_sequences=None):
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json" if json_mode else None,  # forces clean JSON
        stop_sequences=stop_sequences,
    )
    return client.models.generate_content(model=MODEL, contents=contents, config=cfg).text


if __name__ == "__main__":
    contents = []
    add_user_message(contents, "Generate a very short EventBridge rule as json")

    # json_mode=True → Gemini returns raw JSON, no ```json fences, no commentary.
    raw = chat(contents, json_mode=True)
    data = json.loads(raw)                 # parseable straight away
    print("parsed JSON ->", data)
