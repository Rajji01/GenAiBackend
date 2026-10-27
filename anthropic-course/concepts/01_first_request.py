"""
Lesson 01 — "Making your first request" (Anthropic course) → implemented in FREE Gemini.

Anthropic teaches:
    client.messages.create(model, max_tokens, messages)  ->  message.content[0].text
Gemini equivalent:
    client.models.generate_content(model, contents, config)  ->  response.text

Run:
    cd narration-enrichment
    uv run python ../anthropic-course/concepts/01_first_request.py
or standalone:
    pip install google-genai python-dotenv
    # PowerShell:  $env:GEMINI_API_KEY="your-key"     bash: export GEMINI_API_KEY=your-key
    python 01_first_request.py

Get a free key (no card) at https://aistudio.google.com .
"""

from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types

# Anthropic lesson: `.env` holds ANTHROPIC_API_KEY, loaded via python-dotenv.
# Here the SAME idea, different var name: GEMINI_API_KEY. Keep .env in .gitignore.
load_dotenv(Path(__file__).resolve().parents[2] / "narration-enrichment" / ".env")

# Anthropic:  client = Anthropic()          # reads ANTHROPIC_API_KEY from the env
# Gemini:     genai.Client() auto-reads GEMINI_API_KEY (or GOOGLE_API_KEY) from the env.
client = genai.Client()  # == genai.Client(api_key=os.environ["GEMINI_API_KEY"])

# Anthropic lesson used model = "claude-sonnet-4-0".
MODEL = "gemini-2.5-flash"  # free + fast; good for learning.


def single_turn() -> None:
    """The lesson's core example: one user message in, one answer out."""
    # ---- Anthropic version (for comparison) --------------------------------
    # message = client.messages.create(
    #     model=model,
    #     max_tokens=1000,
    #     messages=[{"role": "user", "content": "What is quantum computing? Answer in one sentence"}],
    # )
    # print(message.content[0].text)
    # ---- Gemini version ----------------------------------------------------
    response = client.models.generate_content(
        model=MODEL,
        contents="What is quantum computing? Answer in one sentence",
        config=types.GenerateContentConfig(
            # max_output_tokens == Anthropic's max_tokens: a SAFETY CAP, not a target.
            # The model writes what it thinks is right and stops; it won't pad to the cap.
            max_output_tokens=1000,
        ),
    )

    # Anthropic: message.content[0].text   (content is a LIST of blocks)
    # Gemini:    response.text             (convenience accessor for the text)
    print("Answer:", response.text)

    # The response also carries metadata — here, token usage:
    if response.usage_metadata is not None:
        print(
            "tokens -> prompt:", response.usage_metadata.prompt_token_count,
            "| output:", response.usage_metadata.candidates_token_count,
            "| total:", response.usage_metadata.total_token_count,
        )


def multi_turn() -> None:
    """
    Mirror Anthropic's messages=[{role, content}, ...] conversation list.
    IMPORTANT difference: Gemini's assistant role is "model", NOT "assistant",
    and the text lives under "parts", not "content".
    """
    contents = [
        {"role": "user", "parts": [{"text": "My name is Rajat."}]},
        {"role": "model", "parts": [{"text": "Nice to meet you, Rajat!"}]},  # "model" = Anthropic's "assistant"
        {"role": "user", "parts": [{"text": "What's my name?"}]},
    ]
    response = client.models.generate_content(model=MODEL, contents=contents)
    print("Multi-turn answer:", response.text)


if __name__ == "__main__":
    single_turn()
    print("-" * 40)
    multi_turn()
