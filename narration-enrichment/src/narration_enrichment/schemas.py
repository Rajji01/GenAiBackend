"""
Request/response models for the batch + persistence endpoints (Week 2).
TransactionEnrichment (models.py) stays reserved for the one contract the
LLM itself must satisfy — these are purely API-shape models, same
separation-of-concerns idea as the Java project's DTOs vs entities.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class BatchEnrichRequest(BaseModel):
    # Capped at 50 — a real bank statement could have hundreds of lines,
    # but an unbounded list here is an easy way for one request to burn an
    # entire day's API quota (see Week 2 notes on the free-tier limits).
    narrations: list[str] = Field(..., min_length=1, max_length=50)


class BatchItemResult(BaseModel):
    index: int
    narration: str
    success: bool
    merchant: str | None = None
    category: str | None = None
    transaction_type: str | None = None
    confidence: float | None = None
    error: str | None = None


class BatchEnrichResponse(BaseModel):
    total: int
    succeeded: int
    failed: int
    results: list[BatchItemResult]


class EnrichmentRecordResponse(BaseModel):
    id: int
    narration: str
    merchant: str
    category: str
    transaction_type: str
    confidence: float
    created_at: datetime

    model_config = {"from_attributes": True}  # build directly from the SQLAlchemy object
