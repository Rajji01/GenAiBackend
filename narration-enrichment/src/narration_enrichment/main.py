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
from narration_enrichment.db import get_db, list_enrichments, save_enrichment
from narration_enrichment.models import TransactionEnrichment
from narration_enrichment.rate_limiter import RateLimiter, RateLimitExceededError
from narration_enrichment.schemas import (
    BatchEnrichRequest,
    BatchEnrichResponse,
    BatchItemResult,
    EnrichmentRecordResponse,
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

    # RAG retrieval is an enhancement, not the critical path — if it
    # breaks (embedding call down, bad data in the DB), enrichment must
    # still work exactly as it did before Week 3, just without the extra
    # context. A retrieval bug should never become an enrichment outage.
    context = None
    try:
        query_embedding = rag.embed_text(raw_client, narration, task_type="RETRIEVAL_QUERY")
        similar = rag.find_similar_examples(db, query_embedding)
        context = rag.build_context_block(similar)
    except Exception as exc:  # noqa: BLE001 - degrade, don't fail the request
        logger.warning("rag_retrieval_failed error=%s", exc)

    # Checked right before the actual generative call, not at the top of
    # the route — RAG's retrieval embedding above doesn't count against
    # this quota, only the structured-extraction call does.
    rate_limiter.acquire()
    result = enrich_narration(narration, context=context)

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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
