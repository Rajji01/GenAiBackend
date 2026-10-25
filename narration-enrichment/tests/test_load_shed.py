"""
Hardening H4 — load shedding on the sync enrich path.

The claim under test: beyond the in-flight cap the API says no in
microseconds — before retrieval, before quota math, before the
provider — and the rejection ORDER across the whole gauntlet
(replay → shed → quota → breaker) is what the comments promise.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import narration_enrichment.main as main_module
from narration_enrichment.circuit_breaker import llm_breaker
from narration_enrichment.db import Base, get_db
from narration_enrichment.load_shed import InFlightLimiter, LoadShedError, enrich_shed
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


def _result() -> TransactionEnrichment:
    return TransactionEnrichment(
        merchant="Swiggy", category="food_delivery", transaction_type="upi",
        confidence=0.9, human_narration="Food order at Swiggy",
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


def _saturate():
    for _ in range(enrich_shed._max):
        enrich_shed.acquire()


# --- the counter itself ----------------------------------------------------------


def test_limiter_counts_acquires_and_releases():
    lim = InFlightLimiter(max_in_flight=2)
    lim.acquire()
    lim.acquire()
    with pytest.raises(LoadShedError):
        lim.acquire()
    lim.release()
    lim.acquire()  # capacity restored
    assert lim.in_flight == 2


def test_double_release_cannot_raise_the_effective_cap():
    lim = InFlightLimiter(max_in_flight=1)
    lim.acquire()
    lim.release()
    lim.release()  # buggy extra release — guarded no-op
    assert lim.in_flight == 0
    lim.acquire()
    with pytest.raises(LoadShedError):
        lim.acquire()  # the cap is still 1, not silently 2


# --- the route under saturation ----------------------------------------------------


def test_saturated_shed_answers_fast_without_touching_anything(monkeypatch):
    _saturate()
    exploding = MagicMock(side_effect=AssertionError("shed must answer before this"))
    with patch("narration_enrichment.rag.embed_text", exploding), patch(
        "narration_enrichment.service._call_llm", exploding
    ):
        r = client.post("/enrich", json={"narration": "UPI/SWIGGY/Payment"})

    assert r.status_code == 503
    assert "load shed" in r.json()["detail"]
    assert r.headers["Retry-After"] == "1"
    assert exploding.call_count == 0


def test_release_restores_service_and_success_path_releases_its_own_slot():
    _saturate()
    enrich_shed.release()  # one slot back

    with patch("narration_enrichment.rag.embed_text", return_value=[0.1] * 8), patch(
        "narration_enrichment.service._call_llm", return_value=_result()
    ):
        first = client.post("/enrich", json={"narration": "UPI/SWIGGY/Payment"})
        # If the route leaked its slot, this second call would shed.
        second = client.post("/enrich", json={"narration": "UPI/SWIGGY/Payment"})

    assert first.status_code == 200
    assert second.status_code == 200


def test_error_paths_release_the_slot_too():
    # A provider failure must not leak capacity — the finally is the
    # guarantee, this is its regression test.
    from google.genai.errors import APIError

    with patch("narration_enrichment.rag.embed_text", return_value=[0.1] * 8), patch(
        "narration_enrichment.service._call_llm",
        side_effect=APIError(code=503, response_json={}, response=None),
    ):
        r = client.post("/enrich", json={"narration": "UPI/SWIGGY/Payment"})
    assert r.status_code == 503
    assert enrich_shed.in_flight == 0


def test_batch_holds_one_slot_and_sheds_when_full():
    _saturate()
    r = client.post("/enrich/batch", json={"narrations": ["UPI/SWIGGY/Payment"]})

    assert r.status_code == 503
    assert "load shed" in r.json()["detail"]


# --- the rejection order, pinned ------------------------------------------------------


def test_replay_is_served_even_at_full_capacity():
    # Order rung 1: a stored idempotent response outranks the shed —
    # replays are free by definition and cost no held thread worth
    # protecting.
    with patch("narration_enrichment.rag.embed_text", return_value=[0.1] * 8), patch(
        "narration_enrichment.service._call_llm", return_value=_result()
    ):
        assert client.post(
            "/enrich", json={"narration": "UPI/SWIGGY/Payment"},
            headers={"Idempotency-Key": "warm"},
        ).status_code == 200

    _saturate()
    r = client.post(
        "/enrich", json={"narration": "UPI/SWIGGY/Payment"},
        headers={"Idempotency-Key": "warm"},
    )

    assert r.status_code == 200
    assert r.headers.get("X-Idempotent-Replay") == "true"


def test_shed_outranks_quota_and_breaker(monkeypatch):
    # Order rung 2: with the shed full, a zero-quota limiter AND an
    # OPEN breaker, the answer is the SHED's — the cheapest no wins.
    monkeypatch.setattr(main_module, "rate_limiter", RateLimiter(per_minute=0, per_day=0))
    for _ in range(llm_breaker._failure_threshold):
        llm_breaker.record_failure()
    _saturate()

    r = client.post("/enrich", json={"narration": "UPI/SWIGGY/Payment"})

    assert r.status_code == 503
    assert "load shed" in r.json()["detail"]


def test_quota_outranks_breaker(monkeypatch):
    # Order rung 3: the limiter sits BEFORE the breaker on purpose
    # (see the comment in service.enrich_narration). With a 1-slot
    # quota and an OPEN breaker: the first call spends the slot and
    # gets the breaker's 503 (documented cost — while the provider is
    # down the quota is worthless anyway); the second call is answered
    # by the QUOTA's 429 even though the circuit is still open.
    monkeypatch.setattr(main_module, "rate_limiter", RateLimiter(per_minute=1, per_day=1))
    for _ in range(llm_breaker._failure_threshold):
        llm_breaker.record_failure()

    with patch("narration_enrichment.rag.embed_text", return_value=[0.1] * 8):
        first = client.post("/enrich", json={"narration": "UPI/SWIGGY/Payment"})
        second = client.post("/enrich", json={"narration": "UPI/SWIGGY/Payment"})

    assert first.status_code == 503
    assert "circuit open" in first.json()["detail"]
    assert second.status_code == 429


def test_breaker_answers_when_shed_and_quota_have_room():
    # Order rung 4: room everywhere except the circuit → the breaker's
    # distinct 503.
    for _ in range(llm_breaker._failure_threshold):
        llm_breaker.record_failure()

    with patch("narration_enrichment.rag.embed_text", return_value=[0.1] * 8):
        r = client.post("/enrich", json={"narration": "UPI/SWIGGY/Payment"})

    assert r.status_code == 503
    assert "circuit open" in r.json()["detail"]
    assert enrich_shed.in_flight == 0  # and the slot was released
