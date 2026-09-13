"""
FastAPI service exposing the narration-enrichment pipeline.

Run: uv run uvicorn narration_enrichment.main:app --reload
Docs: http://127.0.0.1:8000/docs (generated from the Pydantic models below,
same idea as springdoc-openapi in the Java project — free API docs from
code that already exists, not a hand-maintained spec.)
"""

import logging

import httpx
from fastapi import FastAPI, HTTPException
from instructor.core.exceptions import InstructorRetryException
from pydantic import BaseModel, Field

from narration_enrichment.models import TransactionEnrichment
from narration_enrichment.service import enrich_narration

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Narration Enrichment", version="0.1.0")


class EnrichRequest(BaseModel):
    narration: str = Field(..., min_length=3, max_length=500)


@app.post("/enrich", response_model=TransactionEnrichment)
def enrich(request: EnrichRequest) -> TransactionEnrichment:
    try:
        return enrich_narration(request.narration)

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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
