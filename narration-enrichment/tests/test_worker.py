"""
P4 Day 3 — tests for the Worker half.

No FastAPI here: the worker is a plain loop over (DB session, queue,
embed_fn), so the tests drive `process_one_message` / `run_once`
directly against an in-memory SQLite + InMemoryJobQueue + a fake
embed function. The embedding boundary is injected, same seam the
sync-ingest tests mock — no network anywhere.
"""

import pytest
from google.genai.errors import APIError
from httpx import ReadTimeout
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from narration_enrichment.db import (
    JOB_DEAD,
    JOB_DONE,
    JOB_FAILED,
    JOB_PROCESSING,
    JOB_QUEUED,
    Base,
    create_ingest_job,
    get_ingest_job,
)
from narration_enrichment.job_queue import InMemoryJobQueue
from narration_enrichment.policy_ingest import compute_checksum
from narration_enrichment.worker import process_one_message, run_once


_test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


@event.listens_for(_test_engine, "connect")
def _fk_on(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


_TestSessionLocal = sessionmaker(bind=_test_engine, autoflush=False, autocommit=False)
Base.metadata.create_all(_test_engine)

FAKE_EMBEDDING = [0.1] * 256
MAX_ATTEMPTS = 3


def _ok_embed(text: str) -> list[float]:
    return FAKE_EMBEDDING


@pytest.fixture()
def db():
    with _test_engine.begin() as conn:
        conn.execute(Base.metadata.tables["policy_chunks"].delete())
        conn.execute(Base.metadata.tables["policy_docs"].delete())
        conn.execute(Base.metadata.tables["ingest_jobs"].delete())
    session = _TestSessionLocal()
    try:
        yield session
    finally:
        session.close()


def _seed(db, *, job_id="job-1", doc_id="d1", content="hello worker world", status=JOB_QUEUED, attempts=0):
    job = create_ingest_job(
        db,
        job_id=job_id,
        doc_id=doc_id,
        title="t",
        content=content,
        checksum=compute_checksum(content),
    )
    if status != JOB_QUEUED or attempts:
        job.status = status
        job.attempts = attempts
        db.commit()
    return job


def _enqueue(db, queue, **kwargs):
    job = _seed(db, **kwargs)
    queue.send(job.id)
    return job, queue.receive()[0]


# --- the happy path ----------------------------------------------------------


def test_happy_path_job_goes_done_chunks_land_message_acked(db):
    queue = InMemoryJobQueue()
    job, msg = _enqueue(db, queue, content="A" * 1200)

    outcome = process_one_message(db, queue, msg, embed_fn=_ok_embed, max_attempts=MAX_ATTEMPTS)

    assert outcome == JOB_DONE
    row = get_ingest_job(db, job.id)
    db.refresh(row)
    assert row.status == JOB_DONE
    assert row.attempts == 1
    assert row.error is None
    assert row.started_at is not None
    assert row.finished_at is not None
    # The actual work product: the policy doc + its chunks exist, via
    # the SAME upsert the sync route uses.
    with _test_engine.connect() as conn:
        chunks = conn.execute(Base.metadata.tables["policy_chunks"].select()).fetchall()
    assert len(chunks) == 3  # 1200 chars at default chunk_size/overlap
    assert queue.depth() == 0  # acked


def test_run_once_drains_a_batch_and_reports_handled_count(db):
    queue = InMemoryJobQueue()
    for i in range(3):
        _seed(db, job_id=f"job-{i}", doc_id=f"d{i}", content=f"doc body {i}")
        queue.send(f"job-{i}")

    handled = run_once(db, queue, embed_fn=_ok_embed, max_attempts=MAX_ATTEMPTS)

    assert handled == 3
    assert queue.depth() == 0
    for i in range(3):
        row = get_ingest_job(db, f"job-{i}")
        db.refresh(row)
        assert row.status == JOB_DONE


def test_run_once_on_empty_queue_returns_zero(db):
    queue = InMemoryJobQueue()

    assert run_once(db, queue, embed_fn=_ok_embed, max_attempts=MAX_ATTEMPTS) == 0


# --- dedup: the claim is the idempotent-consumer check ------------------------


def test_duplicate_delivery_for_done_job_is_dropped_without_touching_it(db):
    queue = InMemoryJobQueue()
    job, msg = _enqueue(db, queue)
    process_one_message(db, queue, msg, embed_fn=_ok_embed, max_attempts=MAX_ATTEMPTS)

    # The same job_id arrives again (sweep raced the send, or SQS
    # redelivered). The claim matches zero rows → drop + ack.
    queue.send(job.id)
    dup = queue.receive()[0]
    outcome = process_one_message(db, queue, dup, embed_fn=_ok_embed, max_attempts=MAX_ATTEMPTS)

    assert outcome is None
    row = get_ingest_job(db, job.id)
    db.refresh(row)
    assert row.status == JOB_DONE
    assert row.attempts == 1  # the duplicate did NOT burn an attempt
    assert queue.depth() == 0


def test_delivery_for_processing_job_is_dropped(db):
    queue = InMemoryJobQueue()
    job, msg = _enqueue(db, queue, status=JOB_PROCESSING, attempts=1)

    outcome = process_one_message(db, queue, msg, embed_fn=_ok_embed, max_attempts=MAX_ATTEMPTS)

    assert outcome is None
    row = get_ingest_job(db, job.id)
    db.refresh(row)
    assert row.status == JOB_PROCESSING
    assert row.attempts == 1


def test_message_for_unknown_job_id_is_acked_not_crashed(db):
    queue = InMemoryJobQueue()
    queue.send("ghost-job")
    msg = queue.receive()[0]

    outcome = process_one_message(db, queue, msg, embed_fn=_ok_embed, max_attempts=MAX_ATTEMPTS)

    assert outcome is None
    assert queue.depth() == 0


# --- the transient whitelist ---------------------------------------------------


def _transient_embed(text: str) -> list[float]:
    raise APIError(code=503, response_json={}, response=None)


def test_transient_failure_goes_failed_with_error_kept(db):
    queue = InMemoryJobQueue()
    job, msg = _enqueue(db, queue)

    outcome = process_one_message(db, queue, msg, embed_fn=_transient_embed, max_attempts=MAX_ATTEMPTS)

    assert outcome == JOB_FAILED
    row = get_ingest_job(db, job.id)
    db.refresh(row)
    assert row.status == JOB_FAILED
    assert row.attempts == 1
    assert "APIError" in row.error
    assert queue.depth() == 0  # acked — the retry wake-up is the sweep's job
    # And no partial work leaked: the all-or-nothing ingest contract held.
    with _test_engine.connect() as conn:
        assert conn.execute(Base.metadata.tables["policy_docs"].select()).fetchall() == []


def test_timeout_counts_as_transient(db):
    def _timeout_embed(text: str) -> list[float]:
        raise ReadTimeout("embed timed out")

    queue = InMemoryJobQueue()
    job, msg = _enqueue(db, queue)

    outcome = process_one_message(db, queue, msg, embed_fn=_timeout_embed, max_attempts=MAX_ATTEMPTS)

    assert outcome == JOB_FAILED


def test_failed_job_is_claimable_again_and_can_succeed(db):
    # The sweep (Day 5) re-enqueues a FAILED job; this pins the state
    # machine's FAILED → PROCESSING → DONE leg with attempts carrying over.
    queue = InMemoryJobQueue()
    job, msg = _enqueue(db, queue, status=JOB_FAILED, attempts=1)

    outcome = process_one_message(db, queue, msg, embed_fn=_ok_embed, max_attempts=MAX_ATTEMPTS)

    assert outcome == JOB_DONE
    row = get_ingest_job(db, job.id)
    db.refresh(row)
    assert row.attempts == 2
    assert row.error is None  # DONE clears the stale failure reason


def test_transient_failure_at_attempt_budget_goes_dead(db):
    # attempts counts claims: seeded at 2, this claim makes it 3 ==
    # max_attempts, so a transient failure now is out of budget → DEAD.
    queue = InMemoryJobQueue()
    job, msg = _enqueue(db, queue, status=JOB_FAILED, attempts=2)

    outcome = process_one_message(db, queue, msg, embed_fn=_transient_embed, max_attempts=MAX_ATTEMPTS)

    assert outcome == JOB_DEAD
    row = get_ingest_job(db, job.id)
    db.refresh(row)
    assert row.status == JOB_DEAD
    assert row.attempts == 3


# --- deterministic failures never retry ----------------------------------------


def test_empty_content_goes_dead_immediately_not_failed(db):
    # A whitespace-only body reached the table (the API rejects these
    # at intake, but defense-in-depth: a direct DB seed or a future
    # bug could park one). Retrying it would fail identically forever
    # — ValueError is not on the transient whitelist, so first attempt
    # goes straight to DEAD.
    queue = InMemoryJobQueue()
    job, msg = _enqueue(db, queue, content="   \n  ")

    outcome = process_one_message(db, queue, msg, embed_fn=_ok_embed, max_attempts=MAX_ATTEMPTS)

    assert outcome == JOB_DEAD
    row = get_ingest_job(db, job.id)
    db.refresh(row)
    assert row.attempts == 1
    assert "ValueError" in row.error


def test_unexpected_exception_goes_dead_not_retried(db):
    # Retryable is an explicit list, never a default. A RuntimeError
    # from the embed boundary is unknown territory — park it DEAD with
    # the reason preserved for a human, don't burn quota re-running it.
    def _broken_embed(text: str) -> list[float]:
        raise RuntimeError("something nobody whitelisted")

    queue = InMemoryJobQueue()
    job, msg = _enqueue(db, queue)

    outcome = process_one_message(db, queue, msg, embed_fn=_broken_embed, max_attempts=MAX_ATTEMPTS)

    assert outcome == JOB_DEAD
    row = get_ingest_job(db, job.id)
    db.refresh(row)
    assert "RuntimeError" in row.error


def test_non_transient_api_error_code_goes_dead(db):
    # A 400 from the embedding provider means the REQUEST is wrong —
    # same request will 400 forever. Only 429/503/504 are transient.
    def _bad_request_embed(text: str) -> list[float]:
        raise APIError(code=400, response_json={}, response=None)

    queue = InMemoryJobQueue()
    job, msg = _enqueue(db, queue)

    outcome = process_one_message(db, queue, msg, embed_fn=_bad_request_embed, max_attempts=MAX_ATTEMPTS)

    assert outcome == JOB_DEAD
