"""
The schema that boundary-validates every LLM call in this project.

This is the answer to Day 2: instead of trusting the model to write correct
JSON as text and hoping json.loads() doesn't blow up, we hand the LLM SDK a
schema and let it force the model's output to match — or fail loudly and
retry, never silently pass through something wrong-shaped.
"""

from typing import Literal

from pydantic import BaseModel, Field


class TransactionEnrichment(BaseModel):
    merchant: str = Field(
        ..., description="The merchant or counterparty name, cleaned up for a human to read."
    )
    category: Literal["food_delivery", "shopping", "salary", "transfer", "other"] = Field(
        ..., description="Best-fit category for this transaction."
    )
    transaction_type: str = Field(
        ..., description='The payment rail, e.g. "UPI", "NEFT", "POS".'
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Model's confidence in this extraction, 0 to 1."
    )
