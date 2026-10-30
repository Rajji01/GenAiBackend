"""
Lesson 06 — "Prefilling + stop sequences" (clean structured output) — CLAUDE version.
Pairs with 06_prefill_stop.py (Gemini). Explainer: 06_prefill_stop.md.

Goal: get RAW data (JSON/code) with no markdown fences and no explanatory prose.

The course's trick: prefill the assistant turn with "```json" (so Claude thinks it already opened a
code block) + a stop_sequence "```" (so it stops before closing it). BUT on current Claude models
assistant PREFILL is REMOVED → a last-assistant-turn prefill returns 400. The modern replacement is
structured output (output_config.format / Instructor) or a plain "JSON only" system prompt. This
file shows both: the course's prefill (expect 400) and a working modern version.

Run:
    C:/.../Python313/python.exe anthropic-course/concepts/06_prefill_stop_claude.py
"""

import json
from pathlib import Path
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv(Path(__file__).resolve().parents[2] / "narration-enrichment" / ".env")
client = Anthropic()
MODEL = "claude-haiku-5-5"


def text_of(message):  # Claude-5 thinks first → pick the text block, not content[0]
    return next((b.text for b in message.content if getattr(b, "type", None) == "text"), "")


def add_user_message(messages, text):
    messages.append({"role": "user", "content": text})


def add_assistant_message(messages, text):
    messages.append({"role": "assistant", "content": text})


def chat(messages, system=None, stop_sequences=None):
    params = {"model": MODEL, "max_tokens": 1000, "messages": messages}
    if system:
        params["system"] = system
    if stop_sequences:
        params["stop_sequences"] = stop_sequences
    return text_of(client.messages.create(**params))


if __name__ == "__main__":
    # --- The course's way: prefill "```json" + stop "```" (REMOVED on current Claude) ----------
    try:
        messages = []
        add_user_message(messages, "Generate a very short EventBridge rule as json")
        add_assistant_message(messages, "```json")          # <-- last-assistant prefill
        print("prefill result:", chat(messages, stop_sequences=["```"]))
    except Exception as e:
        print(f"prefill rejected -> {type(e).__name__}: {e}")
        print("(Current Claude removed assistant prefill. Use structured output / a system prompt.)\n")

    # --- Modern, working way: a "JSON only" system prompt + stop_sequence ----------------------
    messages = []
    add_user_message(messages, "Generate a very short EventBridge rule as json")
    raw = chat(
        messages,
        system="Output ONLY valid JSON. No markdown fences, no commentary, no leading text.",
        stop_sequences=["```"],
    )
    data = json.loads(raw.strip())                          # clean + parseable
    print("parsed JSON ->", data)
    # First-class alternative on Claude: structured outputs (output_config.format) — the same thing
    # my P1 does with Instructor + Pydantic (schema-forced, validated).
