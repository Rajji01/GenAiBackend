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


class IngestAsyncResponse(BaseModel):
    """P4 Day 2 — the 202 (or 200-unchanged) body for
    POST /policies/ingest-async. `unchanged=True` only on the
    checksum fast-path where a DONE job for the same bytes already
    exists — same honest flag the sync route returns."""

    job_id: str
    doc_id: str
    status: str
    unchanged: bool = False


class IngestJobStatusResponse(BaseModel):
    """P4 Day 2 — GET /jobs/{job_id}. A thin projection of the
    ingest_jobs row; `content` is deliberately NOT echoed back
    (potentially large, and the caller already has it)."""

    model_config = {"from_attributes": True}

    job_id: str
    doc_id: str
    status: str
    attempts: int
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class OpsIngestResponse(BaseModel):
    """P4 Day 5 — GET /ops/ingest. The backpressure dashboard:
    queue_depth is visible+in-flight on the work queue; dlq_depth is
    None (not 0) when no DLQ exists, so 'empty DLQ' and 'no DLQ' are
    distinguishable; jobs carries every status with explicit zeros;
    oldest_queued_age_seconds is the staleness headline — None on an
    empty QUEUED set."""

    queue_depth: int
    dlq_depth: int | None = None
    jobs: dict[str, int]
    oldest_queued_age_seconds: float | None = None


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


# --- P3 chat endpoints -----------------------------------------------------

class ChatSessionResponse(BaseModel):
    session_id: str
    created_at: datetime


class ChatMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000,
                         description="One user message. Trimmed silently on save.")


class ChatReply(BaseModel):
    """The response shape for POST /chat/{session_id}/message.

    `cited_*` are populated from GROUND TRUTH retrieval by the
    service layer, never from the LLM's own output — same rule as
    P2's `policy_citations` on TransactionEnrichment. On the Day-3
    stubbed path both lists are empty (no retrieval wired yet).
    """
    answer: str
    cited_enrichment_ids: list[int] = Field(default_factory=list)
    cited_policy_chunk_ids: list[int] = Field(default_factory=list)
    # P5 Day 3 — the earned tool-trail: the tools the service ACTUALLY
    # executed successfully for this reply, in call order, from the
    # executor's own record (never from anything the model claimed).
    tools_used: list[str] = Field(default_factory=list)


class ChatTurnResponse(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime
    # Deliberately kept as raw JSON text — the shape ("list[int]" vs
    # "list[objects]") may evolve as citations grow richer; a
    # loose text field keeps old readers working when it does.
    retrieved_enrichment_ids: str | None = None
    retrieved_policy_chunk_ids: str | None = None

    model_config = {"from_attributes": True}


class ChatSessionHistory(BaseModel):
    session_id: str
    created_at: datetime
    last_active_at: datetime
    turns: list[ChatTurnResponse]


# --- P3 Day 5 eval-as-a-system --------------------------------------------

class EvalResultDetail(BaseModel):
    """One case's outcome from one run. Same shape whether it comes
    back from GET /eval/history?case_id=... or from a full run's
    detail listing."""

    case_id: str
    passed: bool
    expected: str      # JSON text, forwarded as-is
    actual: str        # JSON text, forwarded as-is
    latency_ms: int | None = None
    error: str | None = None
    run_started_at: datetime      # bubbled up via the JOIN so a
                                  # caller can build a timeline

    model_config = {"from_attributes": True}


class EvalCasePassRate(BaseModel):
    case_id: str
    passed: int
    total: int


class EvalHistoryResponse(BaseModel):
    """Either the per-case detail history (when case_id is passed)
    or the pass-rate rollup across every case (when it isn't). Two
    top-level lists rather than a discriminated union because
    consumers can render each independently without unwrapping."""

    per_case_rollup: list[EvalCasePassRate] = Field(default_factory=list)
    details: list[EvalResultDetail] = Field(default_factory=list)


# --- P6 disputes -----------------------------------------------------------

class DisputeCreateRequest(BaseModel):
    # enrichment_id optional: an "unrecognized transaction" claim may
    # reference a txn the user can't identify by id. claim_text capped
    # same as chat messages.
    enrichment_id: int | None = None
    claim_text: str = Field(..., min_length=5, max_length=2000,
                            description="The user's dispute, in their own words. Treated as DATA in every prompt (P6_DESIGN §8).")


class AgentStepResponse(BaseModel):
    step_index: int
    action: str
    tool_name: str | None = None
    tool_args: str | None = None        # JSON text, forwarded as-is
    observation: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class DisputeResponse(BaseModel):
    dispute_id: str
    status: str
    dispute_class: str | None = None
    claim_text: str
    enrichment_id: int | None = None
    escalation_reason: str | None = None
    rejection_reason: str | None = None
    proposal_json: str | None = None    # the typed ResolutionProposal, serialized
    llm_calls_used: int
    created_at: datetime
    resolved_at: datetime | None = None


class DisputeDetail(DisputeResponse):
    steps: list[AgentStepResponse] = Field(default_factory=list)


class DisputeRejectRequest(BaseModel):
    # A rejection without a reason is useless to the next human who
    # reads the dispute — and "reason required" is also what keeps
    # the reject route from being a one-click dismissal habit.
    reason: str = Field(..., min_length=3, max_length=1000)
