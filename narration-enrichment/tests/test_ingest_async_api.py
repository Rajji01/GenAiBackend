"""
P4 Day 2 — integration tests for the async-ingest API half:
  POST /policies/ingest-async   (202 + job_id, dedup fast-paths, 429 valve)
  GET  /jobs/{job_id}           (status projection, 404 on missing)

Same harness as test_policy_api.py: real FastAPI app through
TestClient, in-memory SQLite via StaticPool, per-test dependency
override. No embedding mock needed — the WHOLE POINT of Day 2 is
that the API half never touches the embedding provider; if any test
here triggered an embed call, that would itself be the bug.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from narration_enrichment import auth, config, job_queue
from narration_enrichment.db import (
    JOB_DONE,
    JOB_QUEUED,
    Base,
    create_ingest_job,
    get_db,
    get_ingest_job,
    insert_api_key,
)
from narration_enrichment.main import app
from narration_enrichment.policy_ingest import compute_checksum


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


def _override_get_db():
    db = _TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


client = TestClient(app)

RAW_KEY = "test-raw-key-ingest-async"
HEADERS = {"X-API-Key": RAW_KEY}


@pytest.fixture(autouse=True)
def _db_override():
    # Same install-then-restore dance as test_policy_api.py — never
    # clobber another module's override at import time.
    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield
    finally:
        if previous is not None:
            app.dependency_overrides[get_db] = previous
        else:
            app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def _clean_tables_and_seed_key():
    with _test_engine.begin() as conn:
        conn.execute(Base.metadata.tables["ingest_jobs"].delete())
        conn.execute(Base.metadata.tables["api_keys"].delete())
    db = _TestSessionLocal()
    try:
        insert_api_key(db, key_hash=auth.hash_key(RAW_KEY), label="ingest-async-tests")
    finally:
        db.close()
    yield


@pytest.fixture(autouse=True)
def _fresh_queue():
    # Each test starts with an empty in-memory queue — a leftover
    # message from a previous test would make depth assertions lie.
    job_queue._reset_for_tests()
    yield
    job_queue._reset_for_tests()


def _ingest_async(doc_id: str = "d1", title: str = "t", content: str = "hello async world"):
    return client.post(
        "/policies/ingest-async",
        json={"doc_id": doc_id, "title": title, "content": content},
        headers=HEADERS,
    )


# --- auth posture ----------------------------------------------------------


def test_ingest_async_requires_api_key():
    r = client.post(
        "/policies/ingest-async",
        json={"doc_id": "d1", "title": "t", "content": "body"},
    )
    assert r.status_code == 401


def test_job_status_requires_api_key():
    r = client.get("/jobs/whatever")
    assert r.status_code == 401


# --- the happy path ---------------------------------------------------------


def test_ingest_async_returns_202_creates_queued_job_and_enqueues_hint():
    r = _ingest_async(doc_id="merchant_map", content="A" * 1200)

    assert r.status_code == 202
    body = r.json()
    assert body["doc_id"] == "merchant_map"
    assert body["status"] == JOB_QUEUED
    assert body["unchanged"] is False

    # The job row is the source of truth…
    db = _TestSessionLocal()
    try:
        job = get_ingest_job(db, body["job_id"])
        assert job is not None
        assert job.status == JOB_QUEUED
        assert job.attempts == 0
        assert job.checksum == compute_checksum("A" * 1200)
        assert job.content == "A" * 1200
    finally:
        db.close()

    # …and the queue holds exactly one hint carrying that row's id.
    q = job_queue.get_queue()
    assert q.depth() == 1
    assert q.receive()[0].job_id == body["job_id"]


def test_job_status_projects_the_row_without_echoing_content():
    job_id = _ingest_async().json()["job_id"]

    r = client.get(f"/jobs/{job_id}", headers=HEADERS)

    assert r.status_code == 200
    body = r.json()
    assert body["job_id"] == job_id
    assert body["status"] == JOB_QUEUED
    assert body["attempts"] == 0
    assert body["error"] is None
    assert body["started_at"] is None
    assert "content" not in body


def test_job_status_on_missing_job_returns_404():
    r = client.get("/jobs/does-not-exist", headers=HEADERS)

    assert r.status_code == 404
    assert r.json()["detail"] == "Job not found."


# --- idempotency fast-paths (P4_DESIGN.md §6, layer 1) -----------------------


def test_same_bytes_while_queued_returns_the_same_job_without_double_queueing():
    first = _ingest_async(content="stable body")
    second = _ingest_async(content="stable body")

    assert second.status_code == 202
    assert second.json()["job_id"] == first.json()["job_id"]
    # One unit of work queued, not two — the dedup saved a queue slot
    # AND the embedding budget the duplicate would eventually burn.
    assert job_queue.get_queue().depth() == 1


def test_same_bytes_already_done_returns_200_unchanged_with_no_new_job():
    content = "already ingested body"
    db = _TestSessionLocal()
    try:
        done = create_ingest_job(
            db,
            job_id="finished-job",
            doc_id="d1",
            title="t",
            content=content,
            checksum=compute_checksum(content),
        )
        done.status = JOB_DONE
        db.commit()
    finally:
        db.close()

    r = _ingest_async(doc_id="d1", content=content)

    assert r.status_code == 200
    body = r.json()
    assert body["unchanged"] is True
    assert body["job_id"] == "finished-job"
    assert body["status"] == JOB_DONE
    assert job_queue.get_queue().depth() == 0


def test_changed_bytes_for_the_same_doc_id_create_a_new_job():
    first = _ingest_async(doc_id="d1", content="version one")
    second = _ingest_async(doc_id="d1", content="version two")

    assert second.status_code == 202
    assert second.json()["job_id"] != first.json()["job_id"]
    assert job_queue.get_queue().depth() == 2


# --- intake validation + valve -----------------------------------------------


def test_whitespace_only_content_is_rejected_at_intake_as_400():
    # Never park a job the worker is guaranteed to DEAD-letter — the
    # same caller-bug contract as the sync route's 400.
    r = _ingest_async(content="   \n  ")

    assert r.status_code == 400
    assert job_queue.get_queue().depth() == 0


def test_backlog_over_cap_returns_429_with_retry_after(monkeypatch):
    monkeypatch.setenv("INGEST_MAX_BACKLOG", "1")
    config.get_settings.cache_clear()
    try:
        first = _ingest_async(doc_id="d1", content="doc one")
        assert first.status_code == 202

        r = _ingest_async(doc_id="d2", content="doc two")

        assert r.status_code == 429
        assert "Retry-After" in r.headers
        # The refused doc was never recorded as a job — an honest 429
        # means "nothing was accepted", not "accepted but hidden".
        db = _TestSessionLocal()
        try:
            assert get_ingest_job(db, first.json()["job_id"]) is not None
            rows = db.execute(Base.metadata.tables["ingest_jobs"].select()).fetchall()
            assert len(rows) == 1
        finally:
            db.close()
    finally:
        config.get_settings.cache_clear()


# --- degrade path (P4_DESIGN.md §5: job row = truth, send = hint) -------------


def test_queue_send_failure_still_returns_202_with_a_durable_queued_job():
    class ExplodingQueue:
        def send(self, job_id: str) -> None:
            raise RuntimeError("queue is down")

        def depth(self) -> int:
            return 0

    with patch.object(job_queue, "get_queue", return_value=ExplodingQueue()):
        r = _ingest_async(content="survives queue outage")

    assert r.status_code == 202
    # The work was durably accepted — the row sits QUEUED and the
    # Day-5 recovery sweep will re-send the hint. The caller's 202 is
    # honest because acceptance lives in the DB, not in the queue.
    db = _TestSessionLocal()
    try:
        job = get_ingest_job(db, r.json()["job_id"])
        assert job is not None
        assert job.status == JOB_QUEUED
    finally:
        db.close()
