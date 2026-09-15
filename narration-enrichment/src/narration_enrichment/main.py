"""
FastAPI service exposing the narration-enrichment pipeline.

Run: uv run uvicorn narration_enrichment.main:app --reload
Docs: http://127.0.0.1:8000/docs (generated from the Pydantic models below,
same idea as springdoc-openapi in the Java project — free API docs from
code that already exists, not a hand-maintained spec.)
"""

import logging

import httpx
from fastapi import Depends, FastAPI, HTTPException
from google.genai.errors import APIError
from instructor.core.exceptions import InstructorRetryException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from narration_enrichment.db import get_db, list_enrichments, save_enrichment
from narration_enrichment.models import TransactionEnrichment
from narration_enrichment.schemas import (
    BatchEnrichRequest,
    BatchEnrichResponse,
    BatchItemResult,
    EnrichmentRecordResponse,
)
from narration_enrichment.service import enrich_narration

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Narration Enrichment", version="0.2.0")


class EnrichRequest(BaseModel):
    narration: str = Field(..., min_length=3, max_length=500)


def _enrich_and_persist(narration: str, db: Session) -> TransactionEnrichment:
    result = enrich_narration(narration)
    save_enrichment(db, narration, result)
    return result


@app.post("/enrich", response_model=TransactionEnrichment)
def enrich(request: EnrichRequest, db: Session = Depends(get_db)) -> TransactionEnrichment:
    try:
        return _enrich_and_persist(request.narration, db)

    except InstructorRetryException as exc:
        # The model never produced a shape our schema accepts, even after
        # retrying. The caller needs to know their input couldn't be
        # processed — this is a 422, not a 500.
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
        # service.py already retried this 3x with backoff if it looked
        # transient (429/503/504) — reaching here means those retries
        # were exhausted, or it was a non-transient provider error
        # (e.g. a genuinely bad request to the API). Either way it's the
        # provider's problem right now, not ours — 503, not 500.
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
