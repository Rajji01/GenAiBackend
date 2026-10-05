"""
P4 Day 5 — tests for the recovery sweep + GET /ops/ingest.

The sweep is a pure decision tree over (job rows, clock, queue), so
most tests drive `run_sweep` directly with a seeded DB and an
explicit `now` — no sleeps, no FastAPI. The /ops tests go through
the app for the auth gate and the response contract.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from google.genai.errors import APIError
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from narration_enrichment import auth, job_queue
from narration_enrichment.db import (
    JOB_DEAD,
    JOB_DONE,
    JOB_FAILED,
    JOB_PROCESSING,
    JOB_QUEUED,
    Base,
    create_ingest_job,
    get_db,
    get_ingest_job,
    insert_api_key,
)
from narration_enrichment.job_queue import InMemoryJobQueue
from narration_enrichment.main import app
from narration_enrichment.policy_ingest import compute_checksum
from narration_enrichment.worker import process_one_message, run_sweep


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

NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)
STALE_QUEUED = 120.0
STALE_PROCESSING = 1800.0
MAX_ATTEMPTS = 3
FAKE_EMBEDDING = [0.1] * 256

RAW_KEY = "test-raw-key-recovery"
HEADERS = {"X-API-Key": RAW_KEY}


def _override_get_db():
    db = _TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


client = TestClient(app)


@pytest.fixture()
def db():
    with _test_engine.begin() as conn:
        conn.execute(Base.metadata.tables["policy_chunks"].delete())
        conn.execute(Base.metadata.tables["policy_docs"].delete())
        conn.execute(Base.metadata.tables["ingest_jobs"].delete())
        conn.execute(Base.metadata.tables["api_keys"].delete())
    session = _TestSessionLocal()
    try:
        yield session
    finally:
        session.close()


def _seed(db, *, job_id, status, age_seconds=0.0, attempts=0, started_age_seconds=None, content=None):
    content = content or f"content of {job_id}"
    job = create_ingest_job(
        db,
        job_id=job_id,
        doc_id=f"doc-{job_id}",
        title="t",
        content=content,
        checksum=compute_checksum(content),
    )
    job.status = status
    job.attempts = attempts
    job.created_at = NOW - timedelta(seconds=age_seconds)
    if started_age_seconds is not None:
        job.started_at = NOW - timedelta(seconds=started_age_seconds)
    db.commit()
    return job


def _sweep(db, queue):
    return run_sweep(
        db,
        queue,
        stale_queued_seconds=STALE_QUEUED,
        stale_processing_seconds=STALE_PROCESSING,
        max_attempts=MAX_ATTEMPTS,
        now=NOW,
    )


# --- the decision tree, leg by leg ------------------------------------------


def test_stale_queued_gets_its_hint_resent_fresh_queued_does_not(db):
    queue = InMemoryJobQueue()
    _seed(db, job_id="stale", status=JOB_QUEUED, age_seconds=STALE_QUEUED + 1)
    _seed(db, job_id="fresh", status=JOB_QUEUED, age_seconds=10)

    actions = _sweep(db, queue)

    assert actions["requeued_stale_queued"] == 1
    assert queue.depth() == 1
    assert queue.receive()[0].job_id == "stale"
    # Status untouched — the sweep re-sends the HINT; only a worker's
    # claim moves the state machine.
    row = get_ingest_job(db, "stale")
    db.refresh(row)
    assert row.status == JOB_QUEUED


def test_stale_processing_is_marked_failed_fresh_processing_untouched(db):
    queue = InMemoryJobQueue()
    _seed(db, job_id="dead-worker", status=JOB_PROCESSING, attempts=1,
          started_age_seconds=STALE_PROCESSING + 1)
    _seed(db, job_id="working", status=JOB_PROCESSING, attempts=1,
          started_age_seconds=60)

    actions = _sweep(db, queue)

    assert actions["failed_stale_processing"] == 1
    dead_worker = get_ingest_job(db, "dead-worker")
    working = get_ingest_job(db, "working")
    db.refresh(dead_worker)
    db.refresh(working)
    # The stale one went FAILED and — attempts < max — was re-enqueued
    # by the SAME sweep's third pass, not left for the next cycle.
    assert dead_worker.status == JOB_FAILED
    assert "presumed dead" in dead_worker.error
    assert actions["requeued_failed"] == 1
    assert queue.receive()[0].job_id == "dead-worker"
    assert working.status == JOB_PROCESSING


def test_failed_under_budget_requeued_failed_at_budget_goes_dead(db):
    queue = InMemoryJobQueue()
    _seed(db, job_id="retryable", status=JOB_FAILED, attempts=1)
    _seed(db, job_id="spent", status=JOB_FAILED, attempts=MAX_ATTEMPTS)

    actions = _sweep(db, queue)

    assert actions["requeued_failed"] == 1
    assert actions["dead_at_budget"] == 1
    assert queue.receive()[0].job_id == "retryable"
    spent = get_ingest_job(db, "spent")
    db.refresh(spent)
    assert spent.status == JOB_DEAD


def test_sweep_on_healthy_state_does_nothing(db):
    queue = InMemoryJobQueue()
    _seed(db, job_id="fresh-q", status=JOB_QUEUED, age_seconds=5)
    _seed(db, job_id="working", status=JOB_PROCESSING, started_age_seconds=30)
    _seed(db, job_id="done", status=JOB_DONE)

    actions = _sweep(db, queue)

    assert actions == {
        "requeued_stale_queued": 0,
        "failed_stale_processing": 0,
        "requeued_failed": 0,
        "dead_at_budget": 0,
    }
    assert queue.depth() == 0


def test_full_cycle_transient_failure_sweep_retry_then_done(db):
    # The whole at-least-once story end to end, no sleeps: a job
    # fails transiently → FAILED; the sweep re-arms it; the worker's
    # next claim succeeds → DONE with attempts=2 and the stale error
    # cleared. This is the Day-5 counterpart of ticketing's
    # "kill the process between commit and publish" outbox proof.
    queue = InMemoryJobQueue()
    job = _seed(db, job_id="bounces", status=JOB_QUEUED, content="A" * 600)
    queue.send(job.id)

    def _transient(text):
        raise APIError(code=503, response_json={}, response=None)

    msg = queue.receive()[0]
    assert process_one_message(db, queue, msg, embed_fn=_transient, max_attempts=MAX_ATTEMPTS) == JOB_FAILED

    actions = _sweep(db, queue)
    assert actions["requeued_failed"] == 1

    msg = queue.receive()[0]
    assert process_one_message(db, queue, msg, embed_fn=lambda t: FAKE_EMBEDDING, max_attempts=MAX_ATTEMPTS) == JOB_DONE

    row = get_ingest_job(db, job.id)
    db.refresh(row)
    assert row.status == JOB_DONE
    assert row.attempts == 2
    assert row.error is None


# --- GET /ops/ingest ----------------------------------------------------------


@pytest.fixture()
def ops_client(db):
    insert_api_key(db, key_hash=auth.hash_key(RAW_KEY), label="recovery-tests")
    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _override_get_db
    job_queue._reset_for_tests()
    try:
        yield client
    finally:
        job_queue._reset_for_tests()
        if previous is not None:
            app.dependency_overrides[get_db] = previous
        else:
            app.dependency_overrides.pop(get_db, None)


def test_ops_ingest_requires_api_key(ops_client):
    assert ops_client.get("/ops/ingest").status_code == 401


def test_ops_ingest_on_empty_state_reports_honest_nulls(ops_client):
    r = ops_client.get("/ops/ingest", headers=HEADERS)

    assert r.status_code == 200
    body = r.json()
    assert body["queue_depth"] == 0
    # No DLQ configured (in-memory queue): null, NOT a fake 0 — same
    # rule as /stats' empty-table average_confidence.
    assert body["dlq_depth"] is None
    assert body["oldest_queued_age_seconds"] is None
    # Every status present with an explicit zero — "is DEAD empty or
    # missing?" must never be ambiguous on an ops surface.
    assert body["jobs"] == {
        "QUEUED": 0, "PROCESSING": 0, "DONE": 0, "FAILED": 0, "DEAD": 0,
    }


def test_ops_ingest_reports_rollups_and_oldest_queued_age(ops_client, db):
    _seed(db, job_id="q-old", status=JOB_QUEUED, age_seconds=300)
    _seed(db, job_id="q-new", status=JOB_QUEUED, age_seconds=5)
    _seed(db, job_id="p1", status=JOB_PROCESSING, started_age_seconds=10)
    _seed(db, job_id="dead1", status=JOB_DEAD, attempts=3)
    job_queue.get_queue().send("q-old")

    r = ops_client.get("/ops/ingest", headers=HEADERS)

    assert r.status_code == 200
    body = r.json()
    assert body["queue_depth"] == 1
    assert body["jobs"]["QUEUED"] == 2
    assert body["jobs"]["PROCESSING"] == 1
    assert body["jobs"]["DEAD"] == 1
    # Seeded 300s ago against the REAL clock inside the route — the
    # age must at least reflect the seeded gap (NOW in this file is
    # in the past relative to datetime.now, so >= 300 holds).
    assert body["oldest_queued_age_seconds"] >= 300
