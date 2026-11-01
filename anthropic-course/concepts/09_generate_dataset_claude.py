"""
Lesson 09 — "Generating test datasets" — CLAUDE version.
Pairs with 09_generate_dataset.py (Gemini). Explainer: 09_generate_dataset.md.

Idea: don't hand-write every eval case — have the LLM GENERATE them. Use a FAST model (Haiku) for
generation. Save to dataset.json to load later.

NOTE (L06 callback): the course parses the JSON with assistant PREFILL ("```json") + stop — that
400s on current Claude. We use the modern path instead: a "JSON only" system prompt + stop_sequences.

Run:
    C:/.../Python313/python.exe anthropic-course/concepts/09_generate_dataset_claude.py
"""

import json
from pathlib import Path
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv(Path(__file__).resolve().parents[2] / "narration-enrichment" / ".env")
client = Anthropic()
MODEL = "claude-haiku-5-5"  # a fast/cheap model is the right tool for generating test data


def text_of(message):
    return next((b.text for b in message.content if getattr(b, "type", None) == "text"), "")


def add_user_message(messages, text):
    messages.append({"role": "user", "content": text})


def chat(messages, system=None, stop_sequences=None):
    params = {"model": MODEL, "max_tokens": 1000, "messages": messages}
    if system:
        params["system"] = system
    if stop_sequences:
        params["stop_sequences"] = stop_sequences
    return text_of(client.messages.create(**params))


GEN_PROMPT = """Generate an evaluation dataset for prompts that produce Python, JSON, or a Regex for \
AWS-related tasks. Return an array of JSON objects, each {"task": "<description>"}.
- each task solvable by a SINGLE Python function, a SINGLE JSON object, or a SINGLE regex
- keep tasks small (not much code)
Generate 3 objects."""


def generate_dataset():
    messages = []
    add_user_message(messages, GEN_PROMPT)
    # modern replacement for the course's prefill+stop:
    raw = chat(
        messages,
        system="Output ONLY a valid JSON array. No markdown fences, no commentary.",
        stop_sequences=["```"],
    )
    return json.loads(raw.strip())


if __name__ == "__main__":
    dataset = generate_dataset()
    print(json.dumps(dataset, indent=2))
    out = Path(__file__).with_name("dataset.json")
    out.write_text(json.dumps(dataset, indent=2))
    print(f"\nSaved {len(dataset)} tasks -> {out}")
