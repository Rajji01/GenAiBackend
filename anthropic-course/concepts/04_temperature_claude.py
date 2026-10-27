"""
Lesson 04 — "Temperature" — CLAUDE (native Anthropic API) version.
Pairs with 04_temperature.py (Gemini port, which actually demos the effect). Explainer: 04_temperature.md.

LIVE-VERIFIED DIVERGENCE: current Claude models (Haiku/Sonnet/Opus 5) REMOVED the temperature knob.
A non-default `temperature` returns HTTP 400 — Anthropic replaced it with adaptive thinking + effort
(output_config). So this file shows the course's pattern AND the honest 400; the real low-vs-high
creativity demo lives in 04_temperature.py (Gemini).

Run:
    C:/.../Python313/python.exe anthropic-course/concepts/04_temperature_claude.py
"""

from pathlib import Path
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv(Path(__file__).resolve().parents[2] / "narration-enrichment" / ".env")
client = Anthropic()
MODEL = "claude-haiku-5-5"


def text_of(message):
    return next((b.text for b in message.content if getattr(b, "type", None) == "text"), "")


def add_user_message(messages, text):  # the course's helper — use it, don't inline message dicts
    messages.append({"role": "user", "content": text})


def chat(messages, system=None, temperature=None):
    """The course's flexible chat + temperature. On Claude-5 a non-default temperature 400s."""
    params = {"model": MODEL, "max_tokens": 1000, "messages": messages}
    if system:
        params["system"] = system
    if temperature is not None:
        params["temperature"] = temperature   # <-- rejected (400) on current Claude models
    message = client.messages.create(**params)
    return text_of(message)


if __name__ == "__main__":
    msgs = []
    add_user_message(msgs, "Give me a one-line sci-fi movie idea.")

    # Default (no temperature) — works fine:
    print("default:", chat(msgs))

    # The course's demo: explicit temperature. Expect a 400 on Claude-5.
    try:
        print("temp=0.0:", chat(msgs, temperature=0.0))
    except Exception as e:
        print(f"\nClaude-5 rejected temperature -> {type(e).__name__}: {e}")
        print("On current Claude there is NO temperature knob: adaptive thinking is always on, and")
        print("you shape behaviour with `output_config.effort` + the prompt. For the actual")
        print("deterministic-vs-creative demo, run 04_temperature.py (Gemini).")
