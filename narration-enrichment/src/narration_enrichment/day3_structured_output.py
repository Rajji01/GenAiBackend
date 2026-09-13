"""
Day 3 — the fix: Pydantic + Instructor.

Same narrations, same deliberately casual prompt as Day 2. The only
difference: the call now goes through Instructor with a response_model.
Instructor forces the model's output through that schema (via tool-calling
under the hood, not by hoping the model writes correct JSON prose in its
reply), and retries automatically if the first attempt doesn't validate.

Run: uv run python -m narration_enrichment.day3_structured_output
"""

import os

import instructor
from dotenv import load_dotenv
from google import genai
from pydantic import ValidationError

from narration_enrichment.models import TransactionEnrichment

load_dotenv()

MODEL = "gemini-3.6-flash"

NARRATIONS = [
    "UPI/P2M/509912345678/PAYTM/SWIGGY BANGALORE/Payment",
    "NEFT-N123456789-ACME CORP SALARY-MAR2026",
    "POS 4109XXXXXXXX1234 AMAZON.IN BANGALORE IND",
]

# Same deliberately casual prompt as Day 2 — the point is that the schema,
# not careful prompt wording, is what now guarantees the shape.
PROMPT_TEMPLATE = """Look at this bank transaction narration and tell me the
merchant, the category, the transaction type, and how confident you are.

Narration: {narration}
"""


def main() -> None:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is not set. See .env.example.")

    raw_client = genai.Client(api_key=api_key)
    client = instructor.from_genai(raw_client, model=MODEL)

    for narration in NARRATIONS:
        prompt = PROMPT_TEMPLATE.format(narration=narration)
        print("=" * 70)
        print(f"Narration: {narration}")

        try:
            result = client.create(
                response_model=TransactionEnrichment,
                messages=[{"role": "user", "content": prompt}],
                max_retries=3,
            )
        except ValidationError as e:
            print("FAILED even after retries — clean error, not a crash:")
            print(e)
            continue

        print(f"type:             {type(result).__name__}  <- a real Python object, not a dict")
        print(f"merchant:         {result.merchant!r}")
        print(f"category:         {result.category!r}")
        print(f"transaction_type: {result.transaction_type!r}")
        print(f"confidence:       {result.confidence!r}  ({type(result.confidence).__name__})")
        print()


if __name__ == "__main__":
    main()
