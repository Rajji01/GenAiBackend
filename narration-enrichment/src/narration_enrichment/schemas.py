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


class CategoryCount(BaseModel):
    category: str
    count: int


class StatsResponse(BaseModel):
    total_enrichments: int
    average_confidence: float | None
    category_breakdown: list[CategoryCount]
    # Read-only peek at the Week 4 rate limiter's current headroom — the
    # same numbers that determine whether the *next* /enrich call would
    # succeed or get a 429, without actually attempting one.
    rate_limit_remaining_this_minute: int
    rate_limit_remaining_today: int


# --- P2 policy endpoints -------------------------------------------------

class PolicyIngestRequest(BaseModel):
    # doc_id length-capped to match the DB column and to keep it
    # tractable as a URL segment for DELETE /policies/{doc_id}.
    doc_id: str = Field(..., min_length=1, max_length=64,
                        description="Stable caller-chosen id — same id + same content = no-op re-ingest.")
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1,
                         description="Raw text of the policy doc (Markdown / plain text). See P2_DESIGN sec 1 for examples.")


class PolicyIngestResponse(BaseModel):
    doc_id: str
    chunks_ingested: int
    unchanged: bool = Field(
        ...,
        description="true = same doc_id + same content as before, no embedding work done and no chunk row changed.",
    )
    checksum: str


class PolicyDocSummary(BaseModel):
    doc_id: str
    title: str
    source_uri: str | None
    chunk_count: int
    ingested_at: datetime

    model_config = {"from_attributes": True}
