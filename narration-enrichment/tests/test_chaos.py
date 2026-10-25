"""
Hardening H5 — the chaos suite: invariants under COMBINED failure.

Every mechanism is tested alone in its own file. Production failures
arrive in combinations (the post-mortem classic: the mitigation for
fault A amplifies fault B), so this file scripts the combinations and
asserts SYSTEM-level invariants — the PROD_HARDENING.md §5 list, as
executable claims. No network, no sleeps: fault injection is mocks,
time travel is the breaker's internals.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from google.genai.errors import APIError
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import narration_enrichment.main as main_module
from narration_enrichment import auth, chat_service
from narration_enrichment.chat_service import _ChatLLMReply
from narration_enrichment.circuit_breaker import CLOSED, OPEN, llm_breaker
from narration_enrichment.db import (
    JOB_DONE,
    Base,
    append_chat_turn,
    create_chat_session,
    create_ingest_job,
    get_db,
    get_idempotency_record,
    get_ingest_job,
    insert_api_key,
)
from narration_enrichment.job_queue import InMemoryJobQueue
from narration_enrichment.load_shed import enrich_shed
from narration_enrichment.main import app
from narration_enrichment.models import TransactionEnrichment
from narration_enrichment.policy_ingest import compute_checksum
from narration_enrichment.rate_limiter import RateLimiter
from narration_enrichment.worker import process_one_message


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

DEAD = APIError(code=503, response_json={}, response=None)


def _result() -> TransactionEnrichment:
    return TransactionEnrichment(
        merchant="Swiggy", category="food_delivery", transaction_type="upi",
        confidence=0.9, human_narration="Food order at Swiggy",
    )


@pytest.fixture(autouse=True)
def _harness(monkeypatch):
    with _test_engine.begin() as conn:
        for table in ("idempotency_keys", "enrichment_records", "policy_chunks",
                      "policy_docs", "ingest_jobs", "tool_invocations",
                      "chat_turns", "chat_sessions", "api_keys"):
            conn.execute(Base.metadata.tables[table].delete())
    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _override_get_db
    monkeypatch.setattr(main_module, "rate_limiter", RateLimiter(per_minute=1000, per_day=10000))
    try:
        yield
    finally:
        if previous is not None:
            app.dependency_overrides[get_db] = previous
        else:
            app.dependency_overrides.pop(get_db, None)


# --- scenario 1: outage + retrying client with an idempotency key -------------------


def test_outage_with_idempotent_retries_burns_threshold_then_nothing_and_stores_no_garbage():
    # A client retries the SAME request through a full provider outage.
    # Invariants: the provider is hit exactly threshold times (then the
    # breaker answers), every response is a 503, and the idempotency
    # store holds NOTHING — a failure must never become replayable.
    threshold = llm_breaker._failure_threshold
    dead = MagicMock(side_effect=DEAD)
    with patch("narration_enrichment.rag.embed_text", return_value=[0.1] * 8), patch(
        "narration_enrichment.service._call_llm", dead
    ):
        for _ in range(threshold + 3):
            r = client.post(
                "/enrich", json={"narration": "UPI/SWIGGY/Payment"},
                headers={"Idempotency-Key": "storm"},
            )
            assert r.status_code == 503

    assert dead.call_count == threshold  # the retry storm was absorbed
    db = _TestSessionLocal()
    try:
        assert get_idempotency_record(db, "storm") is None  # no garbage stored
    finally:
        db.close()


def test_recovery_after_the_outage_serves_fresh_then_replays():
    # The same client keeps its key through recovery: first call after
    # the provider heals computes + stores; the next replays for free.
    for _ in range(llm_breaker._failure_threshold):
        llm_breaker.record_failure()
    llm_breaker._opened_at -= llm_breaker._cooldown_seconds + 1  # cooldown elapsed

    healthy = MagicMock(return_value=_result())
    with patch("narration_enrichment.rag.embed_text", return_value=[0.1] * 8), patch(
        "narration_enrichment.service._call_llm", healthy
    ):
        first = client.post(
            "/enrich", json={"narration": "UPI/SWIGGY/Payment"},
            headers={"Idempotency-Key": "storm"},
        )
        second = client.post(
            "/enrich", json={"narration": "UPI/SWIGGY/Payment"},
            headers={"Idempotency-Key": "storm"},
        )

    assert first.status_code == 200          # the probe call healed the circuit
    assert llm_breaker.state == CLOSED
    assert second.headers.get("X-Idempotent-Replay") == "true"
    assert healthy.call_count == 1


# --- scenario 2: the worker's fate is not the API's fate ------------------------------


def test_open_circuit_does_not_stop_the_async_worker():
    # The breaker guards the GENERATIVE boundary; the worker's
    # embedding pipeline is a different dependency with its own
    # failure discipline (FAILED/DEAD). An open circuit on chat/enrich
    # must not strand the ingest pipeline.
    for _ in range(llm_breaker._failure_threshold):
        llm_breaker.record_failure()
    assert llm_breaker.state == OPEN

    db = _TestSessionLocal()
    try:
        queue = InMemoryJobQueue()
        job = create_ingest_job(
            db, job_id="during-outage", doc_id="d1", title="t",
            content="policy body text", checksum=compute_checksum("policy body text"),
        )
        queue.send(job.id)
        outcome = process_one_message(
            db, queue, queue.receive()[0],
            embed_fn=lambda text: [0.1] * 8, max_attempts=3,
        )
        assert outcome == JOB_DONE
        row = get_ingest_job(db, job.id)
        db.refresh(row)
        assert row.status == JOB_DONE
    finally:
        db.close()


# --- scenario 3: embedding down ≠ provider down ----------------------------------------


def test_embed_failures_never_trip_the_generative_breaker():
    # Six straight embedding failures (more than the threshold): the
    # enrich calls still 200 (degrade-not-fail, the P2 invariant) and
    # the breaker stays CLOSED — embedding is OUTSIDE its boundary.
    # Tripping on it would take down chat/enrich because a DIFFERENT
    # model's endpoint hiccuped.
    healthy = MagicMock(return_value=_result())
    with patch(
        "narration_enrichment.rag.embed_text",
        side_effect=RuntimeError("embed endpoint down"),
    ), patch("narration_enrichment.service._call_llm", healthy):
        for _ in range(llm_breaker._failure_threshold + 1):
            r = client.post("/enrich", json={"narration": "UPI/SWIGGY/Payment"})
            assert r.status_code == 200
            assert r.json()["policy_citations"] == []

    assert llm_breaker.state == CLOSED


# --- scenario 4: chat's two channels under embed failure --------------------------------


def test_chat_tools_still_work_while_retrieval_is_down():
    # P5's quiet architectural win, now under fault: retrieval needs
    # the embed endpoint, tools need only the DB. With embedding down,
    # a tool-using chat still answers with an earned trail — and with
    # empty citations (ground truth: nothing was retrieved).
    db = _TestSessionLocal()
    try:
        raw = auth.generate_raw_key()
        insert_api_key(db, key_hash=auth.hash_key(raw), label="chaos-chat")
        create_chat_session(db, session_id="chaos-chat", api_key_hash=auth.hash_key(raw))
        append_chat_turn(db, session_id="chaos-chat", role="user", content="how many?")
    finally:
        db.close()

    steps = [
        _ChatLLMReply(action="tool_call", tool_name="count_transactions", arguments={}),
        _ChatLLMReply(action="final_answer", answer="You have 0 on record."),
    ]
    with patch(
        "narration_enrichment.chat_service.rag.embed_text",
        side_effect=RuntimeError("embed endpoint down"),
    ), patch(
        "narration_enrichment.chat_service._client.create", side_effect=steps
    ):
        db = _TestSessionLocal()
        try:
            reply = chat_service.answer_message(
                db, session_id="chaos-chat", user_message="how many?"
            )
        finally:
            db.close()

    assert reply.tools_used == ["count_transactions"]
    assert reply.cited_enrichment_ids == []
    assert llm_breaker.state == CLOSED  # embed failure, again, not the breaker's business


# --- scenario 5: the full-gauntlet recovery drill ----------------------------------------


def test_saturated_and_open_system_recovers_in_the_documented_order():
    # Worst morning imaginable: shed saturated AND circuit open.
    # Recovery must follow the documented physics: freeing threads
    # restores shedding instantly (one request-duration), the circuit
    # needs its cooldown + one probe. Walk it end to end.
    for _ in range(enrich_shed._max):
        enrich_shed.acquire()
    for _ in range(llm_breaker._failure_threshold):
        llm_breaker.record_failure()

    healthy = MagicMock(return_value=_result())
    with patch("narration_enrichment.rag.embed_text", return_value=[0.1] * 8), patch(
        "narration_enrichment.service._call_llm", healthy
    ):
        # Phase 1: full + open → the shed answers (cheapest no).
        r = client.post("/enrich", json={"narration": "UPI/SWIGGY/Payment"})
        assert r.status_code == 503 and "load shed" in r.json()["detail"]

        # Phase 2: threads drain → the breaker answers (still open).
        for _ in range(enrich_shed._max):
            enrich_shed.release()
        r = client.post("/enrich", json={"narration": "UPI/SWIGGY/Payment"})
        assert r.status_code == 503 and "circuit open" in r.json()["detail"]
        assert healthy.call_count == 0  # nothing has reached the provider yet

        # Phase 3: cooldown elapses → one probe heals everything.
        llm_breaker._opened_at -= llm_breaker._cooldown_seconds + 1
        r = client.post("/enrich", json={"narration": "UPI/SWIGGY/Payment"})
        assert r.status_code == 200

    assert llm_breaker.state == CLOSED
    assert enrich_shed.in_flight == 0
