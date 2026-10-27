"""
Lesson 04 — "Temperature" — GEMINI port (THIS is the one that actually demos the effect).
Pairs with 04_temperature_claude.py. Explainer: 04_temperature.md.

Temperature = the creativity dial over the sampling step: low -> deterministic (picks the top
token), high -> spreads probability -> variety. Gemini keeps the knob (0.0–2.0); current Claude
models removed it (see the _claude file).

Run:
    C:/.../Python313/python.exe anthropic-course/concepts/04_temperature.py
"""

from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv(Path(__file__).resolve().parents[2] / "narration-enrichment" / ".env")
client = genai.Client()
MODEL = "gemini-2.5-flash"


def add_user_message(contents, text):  # the course's helper — use it, don't inline message dicts
    contents.append({"role": "user", "parts": [{"text": text}]})


def chat(contents, system=None, temperature=1.0):
    """The course's flexible chat + a temperature knob (Gemini carries it in the config)."""
    cfg = types.GenerateContentConfig(temperature=temperature, system_instruction=system)
    return client.models.generate_content(model=MODEL, contents=contents, config=cfg).text


if __name__ == "__main__":
    prompt = []
    add_user_message(prompt, "Give me a one-line sci-fi movie idea.")

    print("=== temperature 0.0 (deterministic — twice, expect near-identical) ===")
    print("1:", chat(prompt, temperature=0.0))
    print("2:", chat(prompt, temperature=0.0))

    print("\n=== temperature 1.0 (creative — twice, expect variety) ===")
    print("1:", chat(prompt, temperature=1.0))
    print("2:", chat(prompt, temperature=1.0))

    # Takeaway: low temp for extraction/coding/moderation; high for brainstorming/creative.
    # Temperature changes the PROBABILITY of variety, it doesn't guarantee different text.
