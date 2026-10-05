"""
P4 Day 3 — the Worker half of the split.

Run:  uv run python -m narration_enrichment.worker

A separate PROCESS from the API (`uvicorn narration_enrichment.main:app`)
— that separation is the whole point: embedding work that takes minutes
at the live-measured 5/min quota must not share a lifecycle (or an event
loop, or a deploy) with the request path. The two halves meet only at
the DB (source of truth) and the queue (delivery hints). P4_DESIGN.md §2.

The loop's contract per message, in order:

1. **Claim by CAS** — `claim_ingest_job` flips QUEUED|FAILED →
   PROCESSING in one UPDATE and increments `attempts`. Zero rows
   matched means someone else already handled this job (a redelivered
   duplicate, or a sweep raced us): ack the message and drop. This is
   the idempotent-consumer dedup; the worker never checks "have I seen
   this message" — it checks "is this JOB still claimable."
2. **Do the work** by calling the SAME `policy_ingest.ingest` the sync
   route uses — chunk → embed per chunk → atomic upsert. No second
   ingest implementation to drift out of sync; the async pipeline is a
   different *delivery* of the same operation, not a different
   operation. Its checksum fast-path also makes a re-run of an
   already-applied job converge to "unchanged" (idempotency layer 3).
3. **Record the outcome** — DONE on success; on failure the transient
   whitelist decides (P4_DESIGN.md §7):
     - APIError 429/503/504 or an httpx timeout → FAILED while
       attempts < max (the Day-5 sweep re-enqueues it), DEAD at max.
     - Everything else — ValueError (empty content), any other
       APIError code, any unexpected exception — → DEAD immediately.
       Retryable is an explicit list, never a default (ticketing Bug-5
       thinking): retrying a deterministic failure is quota arson.
4. **Ack the message** in every path. The queue's job ended at
   delivery; what happened to the JOB is recorded on the row, and
   FAILED-retry wake-ups are the sweep's to send, not this message's
   to carry.
"""

import logging
import time

import httpx
from google.genai.errors import APIError
from sqlalchemy.orm import Session

from narration_enrichment import rag
from narration_enrichment.config import get_settings
from narration_enrichment.db import (
    JOB_DEAD,
    JOB_DONE,
    JOB_FAILED,
    SessionLocal,
    claim_ingest_job,
    finish_ingest_job,
    get_ingest_job,
)
from narration_enrichment.job_queue import JobQueue, QueueMessage, get_queue
from narration_enrichment.policy_ingest import EmbedFn, ingest

logger = logging.getLogger(__name__)

# The explicit transient whitelist — the same three codes the
# call-level tenacity retry in service.py fires on, because they were
# the three actually hit live (Week 2/3), not a guess.
_TRANSIENT_CODES = {429, 503, 504}


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, APIError) and exc.code in _TRANSIENT_CODES:
        return True
    return False


def process_one_message(
    db: Session,
    queue: JobQueue,
    message: QueueMessage,
    *,
    embed_fn: EmbedFn,
    max_attempts: int,
) -> str | None:
    """Handle one delivery end-to-end. Returns the job's resulting
    status (DONE/FAILED/DEAD), or None when the delivery was a
    duplicate/unknown and was dropped without touching any job.

    Pure function of its inputs apart from the DB + queue writes —
    the loop below and every test call exactly this.
    """
    job_id = message.job_id

    if not claim_ingest_job(db, job_id):
        # Not claimable: already PROCESSING (another delivery is live),
        # already DONE/DEAD (work finished), or the id is unknown
        # (row deleted, or a bogus message). All of them mean the same
        # thing for THIS delivery: ack and walk away.
        logger.info("worker_duplicate_or_unknown_dropped job_id=%s", job_id)
        queue.delete(message)
        return None

    job = get_ingest_job(db, job_id)

    try:
        result = ingest(
            db,
            doc_id=job.doc_id,
            title=job.title,
            content=job.content,
            embed_fn=embed_fn,
            source_uri=job.source_uri,
        )
        finish_ingest_job(db, job_id, status=JOB_DONE)
        logger.info(
            "worker_job_done job_id=%s doc_id=%s chunks=%d unchanged=%s attempts=%d",
            job_id, job.doc_id, result.chunks_ingested, result.unchanged, job.attempts,
        )
        outcome = JOB_DONE

    except Exception as exc:  # noqa: BLE001 - every outcome becomes row state, never a crash
        error = f"{type(exc).__name__}: {exc}"
        if _is_transient(exc) and job.attempts < max_attempts:
            finish_ingest_job(db, job_id, status=JOB_FAILED, error=error)
            logger.warning(
                "worker_job_failed_retryable job_id=%s attempts=%d/%d error=%s",
                job_id, job.attempts, max_attempts, error,
            )
            outcome = JOB_FAILED
        else:
            # Transient-but-out-of-budget AND deterministic failures
            # both land here; the error text preserves which it was.
            finish_ingest_job(db, job_id, status=JOB_DEAD, error=error)
            logger.error(
                "worker_job_dead job_id=%s attempts=%d/%d error=%s",
                job_id, job.attempts, max_attempts, error,
            )
            outcome = JOB_DEAD

    queue.delete(message)
    return outcome


def run_once(
    db: Session,
    queue: JobQueue,
    *,
    embed_fn: EmbedFn,
    max_attempts: int,
    max_messages: int = 10,
) -> int:
    """Drain up to one received batch. Returns how many deliveries
    were handled (including dropped duplicates) — 0 means the queue
    was empty and the caller may sleep."""
    messages = queue.receive(max_messages=max_messages)
    for message in messages:
        process_one_message(
            db, queue, message, embed_fn=embed_fn, max_attempts=max_attempts
        )
    return len(messages)


def main() -> None:  # pragma: no cover - thin process wrapper over run_once
    from narration_enrichment.service import get_raw_client

    settings = get_settings()
    raw_client = get_raw_client()

    def _embed(text: str) -> list[float]:
        return rag.embed_text(raw_client, text, task_type="RETRIEVAL_DOCUMENT")

    queue = get_queue()
    logger.info("worker_started poll_interval=%ss", settings.worker_poll_interval_seconds)
    while True:
        db = SessionLocal()
        try:
            handled = run_once(
                db,
                queue,
                embed_fn=_embed,
                max_attempts=settings.ingest_max_attempts,
            )
        finally:
            db.close()
        if handled == 0:
            time.sleep(settings.worker_poll_interval_seconds)


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    main()
