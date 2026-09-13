"""
Day 2 — deliberately break the naive approach.

We ask the model for JSON and parse the raw text with json.loads(). No
safety net, no retry, no schema. The point is to see, with real output on
a few different narrations, how this actually fails in practice: a markdown
code fence around the JSON, a missing field, a wrong type (confidence as
"high" instead of a number). These are the same three failure modes that
show up with every provider, in every production system that skips
validation.

Run: uv run python -m narration_enrichment.day2_naive_json
"""

import json
import os

from dotenv import load_dotenv
from google import genai

load_dotenv()

MODEL = "gemini-3.6-flash"

NARRATIONS = [
    "UPI/P2M/509912345678/PAYTM/SWIGGY BANGALORE/Payment",
    "NEFT-N123456789-ACME CORP SALARY-MAR2026",
    "POS 4109XXXXXXXX1234 AMAZON.IN BANGALORE IND",
]

# Deliberately naive — no "ONLY JSON", no explicit types, no exact field
# spec. This is closer to what a first attempt actually looks like, and
# it's exactly the freedom that lets the model's formatting vary.
PROMPT_TEMPLATE = """Look at this bank transaction narration and tell me the
merchant, the category, the transaction type, and how confident you are.

Narration: {narration}

Give me this as JSON.
"""


def main() -> None:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is not set. See .env.example.")

    client = genai.Client(api_key=api_key)

    for narration in NARRATIONS:
        prompt = PROMPT_TEMPLATE.format(narration=narration)
        response = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config={"max_output_tokens": 1024},
        )

        raw_text = response.text
        print("=" * 70)
        print(f"Narration: {narration}")
        print("--- Raw model output ---")
        print(raw_text)

        print("--- json.loads() on the raw text, no safety net ---")
        try:
            parsed = json.loads(raw_text)
            print("Parsed OK:", parsed)

            # Parsing succeeding doesn't mean the SHAPE is right. Check the
            # exact contract we asked for in the prompt.
            problems = []
            if "merchant" not in parsed:
                problems.append("merchant is missing entirely")
            elif not isinstance(parsed["merchant"], str):
                problems.append(f"merchant is {type(parsed['merchant']).__name__}, not str")

            if "transaction_type" not in parsed:
                problems.append("transaction_type is missing entirely")

            if "confidence" not in parsed:
                problems.append("confidence is missing entirely")
            elif not isinstance(parsed["confidence"], (int, float)):
                problems.append(
                    f"confidence is {type(parsed['confidence']).__name__} "
                    f"({parsed['confidence']!r}), not a number"
                )

            if problems:
                print("Parsed, but the shape is still wrong:")
                for p in problems:
                    print(f"  - {p}")
            else:
                print("Shape looks correct this time.")
        except json.JSONDecodeError as e:
            print(f"FAILED: json.loads() raised {e.__class__.__name__}: {e}")
        print()


if __name__ == "__main__":
    main()
