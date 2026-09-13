"""
Day 1 — the raw mechanics of an LLM API call.

No structured output yet (that comes Day 3, once we've deliberately broken
the naive approach on Day 2). Today is just: wire the SDK, make one real
call, and actually look at what crosses the wire — the request payload
you're sending, and the token usage you're billed on in the response.

Run: uv run python -m narration_enrichment.day1_raw_call
"""

import json
import os

from dotenv import load_dotenv
from google import genai

load_dotenv()

# Flash: fast and cheap, plenty for seeing the mechanics of a call.
MODEL = "gemini-3.6-flash"

# Real bank-statement narrations look like this — nobody hands you clean
# sentences in this domain. This is exactly the kind of input Project 1
# will eventually turn into structured JSON.
NARRATION = "UPI/P2M/509912345678/PAYTM/SWIGGY BANGALORE/Payment"


def main() -> None:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit(
            "GEMINI_API_KEY is not set.\n"
            "Copy .env.example to .env in this project and put your real key in it."
        )

    client = genai.Client(api_key=api_key)

    prompt = (
        "Here is a bank transaction narration:\n"
        f"{NARRATION}\n\n"
        "In plain English, what was this transaction for?"
    )

    # This dict is (functionally) the JSON body Gemini's API actually
    # receives — the SDK builds exactly this shape from the `contents=`
    # argument passed to generate_content() below. Nothing magic underneath.
    #
    # max_output_tokens=1024, not 300: gemini-3.6-flash is a reasoning model —
    # it spends "thinking" tokens (see thoughts_token_count below) out of the
    # SAME budget before it writes the visible answer. 300 wasn't enough
    # room for both and the answer came back truncated mid-sentence.
    request_payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 1024},
    }

    print("--- Request payload (what actually goes over the wire) ---")
    print(json.dumps(request_payload, indent=2))

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config={"max_output_tokens": 1024},
    )

    print("\n--- Response text ---")
    print(response.text)

    usage = response.usage_metadata
    print("\n--- Usage (this is what you're billed on, and what counts against the context window) ---")
    print(f"input_tokens:    {usage.prompt_token_count}")
    print(f"thinking_tokens: {usage.thoughts_token_count}  <- invisible, but billed and budgeted")
    print(f"output_tokens:   {usage.candidates_token_count}  <- the visible answer above")
    print(f"total_tokens:    {usage.total_token_count}")
    print(f"finish_reason:   {response.candidates[0].finish_reason}")
    print(f"model:           {MODEL}")


if __name__ == "__main__":
    main()
