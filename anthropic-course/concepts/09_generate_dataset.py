"""
Lesson 09 — "Generating test datasets" — GEMINI port.
Pairs with 09_generate_dataset_claude.py. Explainer: 09_generate_dataset.md.

Have a fast model GENERATE the eval dataset, then save it. Gemini's clean-JSON path is
response_mime_type="application/json" (no prefill hack needed).

Run:
    C:/.../Python313/python.exe anthropic-course/concepts/09_generate_dataset.py
"""

import json
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv(Path(__file__).resolve().parents[2] / "narration-enrichment" / ".env")
client = genai.Client()
MODEL = "gemini-2.5-flash"  # fast + cheap, right for data generation


def add_user_message(contents, text):
    contents.append({"role": "user", "parts": [{"text": text}]})


def chat(contents, system=None, json_mode=False):
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json" if json_mode else None,
    )
    return client.models.generate_content(model=MODEL, contents=contents, config=cfg).text


GEN_PROMPT = """Generate an evaluation dataset for prompts that produce Python, JSON, or a Regex for \
AWS-related tasks. Return an array of JSON objects, each {"task": "<description>"}.
- each task solvable by a SINGLE Python function, a SINGLE JSON object, or a SINGLE regex
- keep tasks small (not much code)
Generate 3 objects."""


def generate_dataset():
    contents = []
    add_user_message(contents, GEN_PROMPT)
    raw = chat(contents, json_mode=True)       # clean JSON array, no fences
    return json.loads(raw)


if __name__ == "__main__":
    dataset = generate_dataset()
    print(json.dumps(dataset, indent=2))
    out = Path(__file__).with_name("dataset.json")
    out.write_text(json.dumps(dataset, indent=2))
    print(f"\nSaved {len(dataset)} tasks -> {out}")
