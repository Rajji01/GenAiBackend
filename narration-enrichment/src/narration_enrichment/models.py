"""
The schema that boundary-validates every LLM call in this project.

This is the answer to Day 2: instead of trusting the model to write correct
JSON as text and hoping json.loads() doesn't blow up, we hand the LLM SDK a
schema and let it force the model's output to match — or fail loudly and
retry, never silently pass through something wrong-shaped.
"""

from typing import Literal

from pydantic import BaseModel, Field


class Citation(BaseModel):
    """One policy-chunk citation attached to an enrichment.

    P2 addition. Populated by the service layer from the ground-truth
    retrieval result — never by the LLM directly, even though
    Instructor's function-calling would happily let the model invent
    values here. See P2_DESIGN.md §6 for the "citations are earned,
    not decorative" contract.
    """

    doc_id: str = Field(..., description="Stable id of the policy doc this cite came from.")
    chunk_index: int = Field(..., ge=0, description="0-based position of the chunk in the source doc.")
    snippet: str = Field(
        ..., max_length=280,
        description="Up to a tweet's worth of the chunk text — for display, not the full chunk.",
    )
    similarity_score: float = Field(
        ..., ge=0.0, le=1.0,
        description="Cosine similarity between the narration and this chunk at retrieval time.",
    )


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
    # P2: policy chunks that actually made it into the prompt for this
    # call. default_factory=list (not `= []`) because Pydantic shares
    # mutable defaults across instances the same way plain Python does
    # — a single class-level `[]` would be a shared cross-instance
    # aliasing bug. The service layer overwrites this from the
    # retrieval result even if the LLM's function-call output claims
    # otherwise, per the citation contract.
    policy_citations: list[Citation] = Field(default_factory=list)
