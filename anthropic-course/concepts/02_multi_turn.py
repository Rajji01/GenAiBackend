"""
Lesson 02 — "Multi-turn conversations" — GEMINI port.
Pairs with 02_multi_turn_claude.py. Explainer: 02_multi_turn.md.

Same idea as the Claude version: the API is STATELESS, so YOU keep the history and
resend it every call. Gemini differences: assistant role is "model", text under "parts".

Run:
    cd narration-enrichment
    uv run python ../anthropic-course/concepts/02_multi_turn.py
"""

from pathlib import Path
from dotenv import load_dotenv
from google import genai

# key from narration-enrichment/.env, CWD-independent
load_dotenv(Path(__file__).resolve().parents[2] / "narration-enrichment" / ".env")
client = genai.Client()
MODEL = "gemini-2.5-flash"


# --- the same three helpers, Gemini-shaped --------------------------------
def add_user_message(contents, text):
    contents.append({"role": "user", "parts": [{"text": text}]})


def add_model_message(contents, text):  # Claude's "assistant" == Gemini's "model"
    contents.append({"role": "model", "parts": [{"text": text}]})


def chat(contents):
    """ONE stateless request: send the ENTIRE history, get the next reply's text."""
    resp = client.models.generate_content(model=MODEL, contents=contents)
    return resp.text


if __name__ == "__main__":
    contents = []

    add_user_message(contents, "Define quantum computing in one sentence")
    answer = chat(contents)
    print("A1:", answer)

    add_model_message(contents, answer)           # feed Gemini's own reply back in
    add_user_message(contents, "Write another sentence")
    final_answer = chat(contents)
    print("A2:", final_answer)

# NOTE: Gemini ALSO offers a built-in stateful helper —
#   c = client.chats.create(model=MODEL); c.send_message("..."); c.send_message("...")
# — which keeps the history for you. Doing it manually (above) mirrors how the Anthropic
# course teaches it, and how narration P3's chat_service persists each turn in a DB.
