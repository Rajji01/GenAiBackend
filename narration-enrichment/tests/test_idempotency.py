"""
Hardening H3 — idempotency keys on /enrich (the Stripe contract).

The claim under test: a client that times out and retries with the
same Idempotency-Key costs ONE LLM call and sees ONE canonical
answer. The LLM boundary is mocked at service._call_llm with a
CALL-COUNTING mock, because call count IS the money here.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from google.genai.errors import APIError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import narration_enrichment.main as main_module
from narration_enrichment.db import (
    Base,
    get_db,
    get_idempotency_record,
    store_idempotency_record,
)
from narration_enrichment.main import app
from narration_enrichment.models import TransactionEnrichment
from narration_enrichment.rate_limiter import RateLimiter


_test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSessionLocal = sessionmaker(bind=_test_engine, autoflush=False, autocommit=False)
Base.metadata.create_all(_test_engine)


def _override_get_db():
    db = _TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


client = TestClient(app)


def _result(merchant="Swiggy", confidence=0.9) -> TransactionEnrichment:
    return TransactionEnrichment(
        merchant=merchant,
        category="food_delivery",
        transaction_type="upi",
        confidence=confidence,
        human_narration=f"Food order at {merchant}",
    )


@pytest.fixture(autouse=True)
def _harness(monkeypatch):
    with _test_engine.begin() as conn:
        conn.execute(Base.metadata.tables["idempotency_keys"].delete())
        conn.execute(Base.metadata.tables["enrichment_records"].delete())
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


def _enrich(narration="UPI/SWIGGY/Payment", key=None):
    headers = {"Idempotency-Key": key} if key else {}
    return client.post("/enrich", json={"narration": narration}, headers=headers)


# --- the contract ---------------------------------------------------------------


def test_without_a_key_every_retry_spends_a_fresh_llm_call():
    llm = MagicMock(return_value=_result())
    with patch("narration_enrichment.rag.embed_text", return_value=[0.1] * 8), patch(
        "narration_enrichment.service._call_llm", llm
    ):
        assert _enrich().status_code == 200
        assert _enrich().status_code == 200

    assert llm.call_count == 2  # old behavior, unchanged — the header opts IN


def test_same_key_same_body_costs_one_llm_call_and_replays_verbatim():
    # The second mocked answer is DIFFERENT on purpose: if the route
    # ever re-processed instead of replaying, the response would
    # change and this test would catch it — nondeterministic LLMs are
    # exactly why replay must return the STORED bytes.
    llm = MagicMock(side_effect=[_result(confidence=0.9), _result(confidence=0.1)])
    with patch("narration_enrichment.rag.embed_text", return_value=[0.1] * 8), patch(
        "narration_enrichment.service._call_llm", llm
    ):
        first = _enrich(key="retry-abc")
        second = _enrich(key="retry-abc")

    assert first.status_code == 200
    assert second.status_code == 200
    assert llm.call_count == 1  # ONE spend for two requests
    assert second.json() == first.json()
    assert second.headers.get("X-Idempotent-Replay") == "true"
    assert "X-Idempotent-Replay" not in first.headers


def test_same_key_different_body_is_a_loud_422_with_no_llm_call():
    llm = MagicMock(return_value=_result())
    with patch("narration_enrichment.rag.embed_text", return_value=[0.1] * 8), patch(
        "narration_enrichment.service._call_llm", llm
    ):
        assert _enrich(narration="UPI/SWIGGY/Payment", key="k1").status_code == 200
        r = _enrich(narration="UPI/ZOMATO/Payment", key="k1")

    assert r.status_code == 422
    assert "different request body" in r.json()["detail"]
    assert llm.call_count == 1  # the misuse attempt never reached the provider


def test_failures_are_not_stored_so_a_retry_gets_a_fresh_attempt():
    # First attempt: provider 503 (not stored). Retry with the SAME
    # key: must process again — and this time succeed and store.
    llm = MagicMock(
        side_effect=[APIError(code=503, response_json={}, response=None), _result()]
    )
    with patch("narration_enrichment.rag.embed_text", return_value=[0.1] * 8), patch(
        "narration_enrichment.service._call_llm", llm
    ):
        first = _enrich(key="after-failure")
        second = _enrich(key="after-failure")
        third = _enrich(key="after-failure")

    assert first.status_code == 503
    assert second.status_code == 200
    assert llm.call_count == 2  # 503 attempt + the successful retry
    assert third.status_code == 200
    assert third.headers.get("X-Idempotent-Replay") == "true"


def test_replay_skips_rate_limiter_breaker_and_retrieval_entirely():
    # A replay is free BY DEFINITION: before the limiter, before the
    # breaker, before any embed call. Prove it by making every
    # downstream boundary explosive on the second call — the replay
    # must still 200.
    llm = MagicMock(return_value=_result())
    with patch("narration_enrichment.rag.embed_text", return_value=[0.1] * 8), patch(
        "narration_enrichment.service._call_llm", llm
    ):
        assert _enrich(key="free-replay").status_code == 200

    from narration_enrichment.circuit_breaker import llm_breaker

    for _ in range(llm_breaker._failure_threshold):
        llm_breaker.record_failure()  # circuit now OPEN

    exploding = MagicMock(side_effect=AssertionError("replay must not touch this"))
    with patch("narration_enrichment.rag.embed_text", exploding), patch(
        "narration_enrichment.service._call_llm", exploding
    ):
        r = _enrich(key="free-replay")

    assert r.status_code == 200
    assert r.headers.get("X-Idempotent-Replay") == "true"
    assert exploding.call_count == 0


# --- the race (db-level, the ticketing Day-7 shape) --------------------------------


def test_store_race_returns_the_winners_row():
    db = _TestSessionLocal()
    try:
        winner = store_idempotency_record(
            db, key="raced", request_hash="h1", response_json='{"a": 1}'
        )
        loser = store_idempotency_record(
            db, key="raced", request_hash="h1", response_json='{"a": 2}'
        )
    finally:
        db.close()

    # The loser's write lost the PK race and got the canonical row
    # back — both callers now hold ONE answer.
    assert loser.response_json == winner.response_json == '{"a": 1}'

    db = _TestSessionLocal()
    try:
        assert get_idempotency_record(db, "raced").response_json == '{"a": 1}'
    finally:
        db.close()
