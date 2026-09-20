"""
FastAPI service exposing the narration-enrichment pipeline.

Run: uv run uvicorn narration_enrichment.main:app --reload
Docs: http://127.0.0.1:8000/docs (generated from the Pydantic models below,
same idea as springdoc-openapi in the Java project — free API docs from
code that already exists, not a hand-maintained spec.)
"""

import logging

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from google.genai.errors import APIError
from instructor.core.exceptions import InstructorRetryException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from narration_enrichment import rag
from narration_enrichment.config import get_settings
from narration_enrichment.correlation import (
    HEADER_NAME,
    CorrelationIdLogFilter,
    new_correlation_id,
    set_correlation_id,
)
from narration_enrichment.db import (
    delete_policy_doc,
    get_category_counts,
    get_db,
    get_total_and_average_confidence,
    list_enrichments,
    list_policy_docs,
    save_enrichment,
)
from narration_enrichment.models import Citation, TransactionEnrichment
from narration_enrichment.policy_ingest import ingest as ingest_policy_doc
from narration_enrichment.rate_limiter import RateLimiter, RateLimitExceededError
from narration_enrichment import s3_store
from narration_enrichment.schemas import (
    BatchEnrichRequest,
    BatchEnrichResponse,
    BatchItemResult,
    CategoryCount,
    EnrichmentRecordResponse,
    PolicyDocSummary,
    PolicyIngestRequest,
    PolicyIngestResponse,
    StatsResponse,
)
from narration_enrichment.service import enrich_narration, get_raw_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(correlation_id)s] %(name)s %(message)s",
)
# Real bug, caught live: a filter attached to the ROOT LOGGER via
# addFilter() does NOT run for records from child loggers (service.py's
# logger, rag.py's logger, ...) propagating up to it — Logger.filter()
# is only invoked by the logger that originates the record, while
# propagation calls each ancestor's HANDLERS directly, bypassing the
# ancestor's own Logger.filter(). The filter has to sit on the handler
# instead, since Handler.handle() does check its own filters regardless
# of which logger the record came from. Attaching it to the logger
# looked correct, imported cleanly, and would have raised
# "KeyError: 'correlation_id'" on the very first logger.info() call
# anywhere else in the codebase — confirmed by actually triggering one.
for _handler in logging.getLogger().handlers:
    _handler.addFilter(CorrelationIdLogFilter())
logger = logging.getLogger(__name__)

app = FastAPI(title="Narration Enrichment", version="0.2.0")


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    # No explicit reset/cleanup needed here, unlike the Java track's
    # MDC.remove() in a finally block: Starlette runs each request in its
    # own asyncio Task, and a ContextVar set inside one Task is invisible
    # to every other concurrently running Task — there's no shared,
    # reused thread for a value to leak across. The isolation Java has to
    # earn with a try/finally, asyncio gives for free per-Task.
    incoming = request.headers.get(HEADER_NAME)
    correlation_id = incoming if incoming else new_correlation_id()
    set_correlation_id(correlation_id)
    response = await call_next(request)
    response.headers[HEADER_NAME] = correlation_id
    return response

_settings = get_settings()
rate_limiter = RateLimiter(
    per_minute=_settings.enrich_rate_limit_per_minute,
    per_day=_settings.enrich_rate_limit_per_day,
)


class EnrichRequest(BaseModel):
    narration: str = Field(..., min_length=3, max_length=500)


def _enrich_and_persist(narration: str, db: Session) -> TransactionEnrichment:
    raw_client = get_raw_client()

    # ONE embedding call, TWO cosine searches (past narrations + policy
    # chunks). The embed step is the slowest thing in /enrich, so sharing
    # the query vector across both retrieval targets is the performance
    # rule that keeps P2 from doubling latency vs Week 3 RAG.
    #
    # RAG retrieval is an enhancement, not the critical path — if the
    # embed call fails (provider down, bad data), enrichment must still
    # work exactly as it did before, just without the extra context. Both
    # blocks below therefore log-and-fall-back rather than raising.
    query_embedding: list[float] | None = None
    context: str | None = None
    try:
        query_embedding = rag.embed_text(raw_client, narration, task_type="RETRIEVAL_QUERY")
        similar = rag.find_similar_examples(db, query_embedding)
        context = rag.build_context_block(similar)
    except Exception as exc:  # noqa: BLE001 - degrade, don't fail the request
        logger.warning("rag_past_retrieval_failed error=%s", exc)

    # P2 Day 5: policy retrieval piggybacks on the same query embedding.
    # If the embed call already failed above, query_embedding is None and
    # we skip policy retrieval too — separate tries would just try the
    # same provider a second time in the same second.
    policy_chunks_scored: list[tuple[float, object]] = []
    policy_context: str | None = None
    if query_embedding is not None:
        try:
            policy_chunks_scored = rag.retrieve_policy_chunks(db, query_embedding)
            policy_context = rag.build_policy_context_block(policy_chunks_scored)
        except Exception as exc:  # noqa: BLE001 - degrade, don't fail the request
            logger.warning("rag_policy_retrieval_failed error=%s", exc)

    # Checked right before the actual generative call, not at the top of
    # the route — RAG's retrieval embedding above doesn't count against
    # this quota, only the structured-extraction call does.
    rate_limiter.acquire()
    result = enrich_narration(narration, context=context, policy_context=policy_context)

    # P2 Day 5 — EARN the citations, don't decorate them. Even if
    # Instructor's function-calling wrote a `policy_citations` list from
    # the model's own output, we overwrite it from the ground-truth
    # retrieval result. The model gets to choose the classification; it
    # does NOT get to choose what to cite. This defeats the "cited a
    # chunk that never landed in the prompt" hallucination class.
    result.policy_citations = [
        Citation(
            doc_id=chunk.doc_id,
            chunk_index=chunk.chunk_index,
            snippet=chunk.content[:280],
            similarity_score=score,
        )
        for score, chunk in policy_chunks_scored
    ]

    # Same reasoning in reverse: the user already has their answer at this
    # point. A failure to embed-for-storage should cost future RAG quality
    # for this one row, not the response that's about to be returned.
    embedding = None
    try:
        embedding = rag.embed_text(raw_client, narration, task_type="RETRIEVAL_DOCUMENT")
    except Exception as exc:  # noqa: BLE001 - degrade, don't fail the request
        logger.warning("rag_embedding_failed error=%s", exc)

    save_enrichment(db, narration, result, embedding=embedding)
    return result


@app.post("/enrich", response_model=TransactionEnrichment)
def enrich(request: EnrichRequest, db: Session = Depends(get_db)) -> TransactionEnrichment:
    try:
        return _enrich_and_persist(request.narration, db)

    except RateLimitExceededError as exc:
        logger.warning("enrich_rate_limited scope=%s retry_after=%.1f", exc.scope, exc.retry_after_seconds)
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded ({exc.scope}). Retry after {exc.retry_after_seconds:.0f}s.",
            headers={"Retry-After": str(int(exc.retry_after_seconds) + 1)},
        ) from exc

    except InstructorRetryException as exc:
        # Week 3 bug, found via a live eval run: .create() wraps EVERY
        # underlying failure in InstructorRetryException, including a
        # transient provider error that exhausted service.py's own
        # tenacity retry — not just a genuine shape/validation failure.
        # The real APIError (if any) is in exc.__cause__; without this
        # check, an exhausted 503 was silently reported as "your input
        # was unprocessable" (422) instead of "the provider is down" (503).
        cause = exc.__cause__
        if isinstance(cause, APIError) and cause.code in {429, 503, 504}:
            logger.warning("enrich_provider_error code=%s status=%s", cause.code, cause.status)
            raise HTTPException(
                status_code=503,
                detail="The enrichment provider is temporarily unavailable. Please retry.",
            ) from exc

        logger.warning("enrich_validation_failed error=%s", exc)
        raise HTTPException(
            status_code=422,
            detail="Could not extract structured data from this narration.",
        ) from exc

    except httpx.TimeoutException as exc:
        logger.warning("enrich_timeout error=%s", exc)
        raise HTTPException(
            status_code=504,
            detail="The enrichment provider took too long to respond.",
        ) from exc

    except APIError as exc:
        # Defensive only — real usage never reaches here (.create() always
        # wraps this into InstructorRetryException, handled above), but if
        # a future Instructor version ever changes that, this still maps
        # it to the right status instead of a generic 500.
        logger.warning("enrich_provider_error code=%s status=%s", exc.code, exc.status)
        raise HTTPException(
            status_code=503,
            detail="The enrichment provider is temporarily unavailable. Please retry.",
        ) from exc

    except Exception as exc:  # noqa: BLE001 - deliberate catch-all, see below
        # Anything else is unexpected: log it in full server-side, but
        # never leak the raw exception message to the caller. Same
        # principle as GlobalExceptionHandler's Exception.class handler in
        # the Java project.
        logger.error("enrich_unexpected_error", exc_info=exc)
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred.",
        ) from exc


@app.post("/enrich/batch", response_model=BatchEnrichResponse)
def enrich_batch(request: BatchEnrichRequest, db: Session = Depends(get_db)) -> BatchEnrichResponse:
    # One bad or slow narration must not fail the other 49 — each item is
    # its own try/except, unlike the single-item route above which is
    # allowed to fail the whole request.
    results: list[BatchItemResult] = []
    for index, narration in enumerate(request.narrations):
        try:
            result = _enrich_and_persist(narration, db)
            results.append(BatchItemResult(
                index=index,
                narration=narration,
                success=True,
                merchant=result.merchant,
                category=result.category,
                transaction_type=result.transaction_type,
                confidence=result.confidence,
            ))
        except Exception as exc:  # noqa: BLE001 - per-item isolation, see above
            logger.warning("batch_item_failed index=%d error=%s", index, exc)
            results.append(BatchItemResult(
                index=index,
                narration=narration,
                success=False,
                error=type(exc).__name__,  # class name only — never the raw message
            ))

    succeeded = sum(1 for r in results if r.success)
    return BatchEnrichResponse(
        total=len(results),
        succeeded=succeeded,
        failed=len(results) - succeeded,
        results=results,
    )


@app.get("/enrichments", response_model=list[EnrichmentRecordResponse])
def get_enrichments(limit: int = 20, offset: int = 0, db: Session = Depends(get_db)) -> list[EnrichmentRecordResponse]:
    return list_enrichments(db, limit=limit, offset=offset)


@app.get("/stats", response_model=StatsResponse)
def get_stats(db: Session = Depends(get_db)) -> StatsResponse:
    total, average_confidence = get_total_and_average_confidence(db)
    category_breakdown = [
        CategoryCount(category=category, count=count) for category, count in get_category_counts(db)
    ]
    minute_remaining, day_remaining = rate_limiter.remaining()
    return StatsResponse(
        total_enrichments=total,
        average_confidence=average_confidence,
        category_breakdown=category_breakdown,
        rate_limit_remaining_this_minute=minute_remaining,
        rate_limit_remaining_today=day_remaining,
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# --- P2: policy corpus management ---------------------------------------
#
# Design note: /policies/ingest is a control-plane operation, distinct
# from the /enrich data-plane path. It has its own error mapping:
# failure to embed => 502 (the provider let us down), unchanged =>
# 200 with a truthful `unchanged=true` flag, valid empty content =>
# 400 (caller bug). No rate limiter on this path — the daily-cap
# quota exists to protect /enrich from being starved by a runaway
# batch ingest, and if it applied here too a big fresh corpus ingest
# would eat every enrichment slot for the day. Ingest is a rare,
# planned op; keeping it off the shared quota is deliberate.


@app.post("/policies/ingest", response_model=PolicyIngestResponse)
def policies_ingest(
    request: PolicyIngestRequest, db: Session = Depends(get_db)
) -> PolicyIngestResponse:
    raw_client = get_raw_client()

    def _embed(text: str) -> list[float]:
        return rag.embed_text(raw_client, text, task_type="RETRIEVAL_DOCUMENT")

    # P2 Day 4: upload the raw doc to S3 first, then run the ingest
    # with the resulting URI recorded on the PolicyDoc row. Order
    # matters:
    #   S3 first  → if S3 is down, we bail early with 503, no wasted
    #               embedding budget spent on a doc that would have
    #               ended up sourceless.
    #   Embed after → if embed fails after a successful upload, we
    #               leave at most one orphan S3 object (sweepable
    #               later); no half-embedded chunks in SQLite.
    # If S3 isn't configured (POLICY_S3_BUCKET empty), skip the
    # upload cleanly and record source_uri=None — that's the dev
    # path, exercised by every test in test_policy_api.py.
    source_uri: str | None = None
    if s3_store.is_configured():
        try:
            source_uri = s3_store.put_raw_doc(request.doc_id, request.content)
        except Exception as exc:  # noqa: BLE001
            # boto3 raises many concrete client-error types (BotoCoreError,
            # ClientError, EndpointConnectionError, ...). Catch broadly here
            # and let the S3-specific detail live in the log line; the
            # client just needs to know "storage layer is down, retry."
            logger.warning("policy_doc_s3_upload_failed doc_id=%s error=%s", request.doc_id, exc)
            raise HTTPException(
                status_code=503,
                detail="Policy-doc durable storage is temporarily unavailable. Please retry.",
            ) from exc

    try:
        result = ingest_policy_doc(
            db,
            doc_id=request.doc_id,
            title=request.title,
            content=request.content,
            embed_fn=_embed,
            source_uri=source_uri,
        )
    except ValueError as exc:
        # Empty content or a chunker→0 divergence — 400, caller bug.
        logger.warning("policy_ingest_invalid doc_id=%s error=%s", request.doc_id, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except APIError as exc:
        # Embedding provider failure — abort the ingest (no
        # partial-embed state), tell the caller to retry. Same 503
        # shape as /enrich's provider-error path so the client
        # doesn't need to learn a new error language for this route.
        logger.warning("policy_ingest_provider_error doc_id=%s code=%s", request.doc_id, exc.code)
        raise HTTPException(
            status_code=503,
            detail="The embedding provider is temporarily unavailable. Please retry.",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        logger.error("policy_ingest_unexpected_error doc_id=%s", request.doc_id, exc_info=exc)
        raise HTTPException(status_code=500, detail="An unexpected error occurred.") from exc

    return PolicyIngestResponse(
        doc_id=result.doc_id,
        chunks_ingested=result.chunks_ingested,
        unchanged=result.unchanged,
        checksum=result.checksum,
    )


@app.get("/policies", response_model=list[PolicyDocSummary])
def policies_list(db: Session = Depends(get_db)) -> list[PolicyDocSummary]:
    return [
        PolicyDocSummary(
            doc_id=doc.doc_id,
            title=doc.title,
            source_uri=doc.source_uri,
            chunk_count=count,
            ingested_at=doc.ingested_at,
        )
        for doc, count in list_policy_docs(db)
    ]


@app.delete("/policies/{doc_id}", status_code=204)
def policies_delete(doc_id: str, db: Session = Depends(get_db)) -> None:
    # Idempotent by design — DELETE on a missing doc_id returns 204,
    # not 404. Callers running "delete then re-ingest" flows in a
    # loop don't have to special-case first-time-through.
    delete_policy_doc(db, doc_id)
    # P2 Day 4: also clean up the S3 object if S3 is configured.
    # Kept best-effort — if S3 is down, the DB row is already gone
    # and the S3 object becomes a sweep-later orphan rather than
    # blocking the delete. This is the "durable storage is a cache
    # of the source of truth for reads, not the write authority"
    # framing from P2_DESIGN.md sec 4 applied to the delete path.
    if s3_store.is_configured():
        try:
            s3_store.delete_raw_doc(doc_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("policy_doc_s3_delete_failed doc_id=%s error=%s", doc_id, exc)
