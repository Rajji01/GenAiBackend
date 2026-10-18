"""
Hardening H2 — circuit breaker tests.

Unit half: the state machine against a fake clock (no sleeps, the
rate-limiter testing pattern). Integration half: the real /enrich
route with service._call_llm exploding — prove the sixth request
never reaches the provider, answers fast with 503 + Retry-After, and
that recovery (probe → close) works end to end.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from google.genai.errors import APIError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import narration_enrichment.main as main_module
from narration_enrichment.circuit_breaker import (
    CLOSED,
    HALF_OPEN,
    OPEN,
    CircuitBreaker,
    CircuitOpenError,
    llm_breaker,
)
from narration_enrichment.db import Base, get_db
from narration_enrichment.main import app
from narration_enrichment.rate_limiter import RateLimiter
from narration_enrichment.service import counts_as_provider_down


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _breaker(threshold=3, cooldown=30.0):
    clock = FakeClock()
    return CircuitBreaker(
        failure_threshold=threshold, cooldown_seconds=cooldown, time_fn=clock
    ), clock


# --- the state machine ---------------------------------------------------------


def test_starts_closed_and_allows():
    b, _ = _breaker()
    assert b.state == CLOSED
    b.allow()  # no raise


def test_failures_below_threshold_stay_closed():
    b, _ = _breaker(threshold=3)
    b.record_failure()
    b.record_failure()
    assert b.state == CLOSED
    b.allow()


def test_threshold_consecutive_failures_open_the_circuit():
    b, _ = _breaker(threshold=3, cooldown=30.0)
    for _ in range(3):
        b.record_failure()

    assert b.state == OPEN
    with pytest.raises(CircuitOpenError) as exc:
        b.allow()
    assert 0 < exc.value.retry_after_seconds <= 30.0


def test_a_success_resets_the_consecutive_count():
    # CONSECUTIVE means consecutive: 2 failures + success + 2 failures
    # is not 4 failures. An intermittently-flaky provider should not
    # accumulate toward OPEN across successes.
    b, _ = _breaker(threshold=3)
    b.record_failure()
    b.record_failure()
    b.record_success()
    b.record_failure()
    b.record_failure()

    assert b.state == CLOSED


def test_retry_after_shrinks_as_the_cooldown_elapses():
    b, clock = _breaker(threshold=1, cooldown=30.0)
    b.record_failure()

    with pytest.raises(CircuitOpenError) as first:
        b.allow()
    clock.advance(20.0)
    with pytest.raises(CircuitOpenError) as later:
        b.allow()

    assert later.value.retry_after_seconds < first.value.retry_after_seconds


def test_cooldown_elapsed_grants_exactly_one_probe():
    b, clock = _breaker(threshold=1, cooldown=30.0)
    b.record_failure()
    clock.advance(30.0)

    b.allow()  # the probe — granted
    assert b.state == HALF_OPEN
    with pytest.raises(CircuitOpenError) as exc:
        b.allow()  # everyone else fails fast while the probe is out
    # Told to come back in ~a second, not a whole fresh cooldown —
    # the probe's verdict is moments away.
    assert exc.value.retry_after_seconds <= 1.0


def test_probe_success_closes_and_fully_resets():
    b, clock = _breaker(threshold=2, cooldown=30.0)
    b.record_failure()
    b.record_failure()
    clock.advance(30.0)
    b.allow()  # probe
    b.record_success()

    assert b.state == CLOSED
    # Fully reset: it takes a full threshold again to re-open.
    b.record_failure()
    assert b.state == CLOSED


def test_probe_failure_reopens_with_a_fresh_cooldown():
    b, clock = _breaker(threshold=1, cooldown=30.0)
    b.record_failure()
    clock.advance(30.0)
    b.allow()  # probe
    b.record_failure()  # probe failed

    assert b.state == OPEN
    with pytest.raises(CircuitOpenError) as exc:
        b.allow()
    # FRESH cooldown — close to the full 30, not the dregs of the old one.
    assert exc.value.retry_after_seconds > 25.0


def test_unhappy_but_alive_provider_counts_as_success():
    # The caller's judgement function: a 400 means the provider
    # ANSWERED. Only the transient whitelist + timeouts are "down."
    assert counts_as_provider_down(APIError(code=503, response_json={}, response=None)) is True
    assert counts_as_provider_down(APIError(code=400, response_json={}, response=None)) is False
    import httpx

    assert counts_as_provider_down(httpx.ReadTimeout("slow")) is True
    assert counts_as_provider_down(ValueError("caller bug")) is False


# --- integration: the /enrich route under a dead provider -----------------------


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


@pytest.fixture()
def enrich_harness(monkeypatch):
    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _override_get_db
    # The per-minute quota (5) would mask the breaker across 6+ calls;
    # swap in a permissive limiter — this test is about the breaker.
    monkeypatch.setattr(main_module, "rate_limiter", RateLimiter(per_minute=1000, per_day=10000))
    try:
        yield
    finally:
        if previous is not None:
            app.dependency_overrides[get_db] = previous
        else:
            app.dependency_overrides.pop(get_db, None)


def test_sixth_request_fails_fast_without_touching_the_provider(enrich_harness):
    threshold = llm_breaker._failure_threshold  # 5 from config
    dead_provider = MagicMock(
        side_effect=APIError(code=503, response_json={}, response=None)
    )
    with patch("narration_enrichment.rag.embed_text", return_value=[0.1] * 8), patch(
        "narration_enrichment.service._call_llm", dead_provider
    ):
        # Burn the threshold: each call reaches the provider and 503s.
        for _ in range(threshold):
            r = client.post("/enrich", json={"narration": "UPI/SWIGGY/Payment"})
            assert r.status_code == 503

        # The breaker is now OPEN: the next request must NOT reach the
        # provider at all, and must carry the circuit-open detail +
        # Retry-After.
        r = client.post("/enrich", json={"narration": "UPI/SWIGGY/Payment"})

    assert r.status_code == 503
    assert "circuit open" in r.json()["detail"]
    assert "Retry-After" in r.headers
    assert dead_provider.call_count == threshold  # not threshold + 1


def test_recovery_probe_closes_the_circuit_end_to_end(enrich_harness):
    # Open the breaker directly (unit-tested above), then prove the
    # route-level recovery: after cooldown one request probes the now-
    # healthy provider, succeeds, and the circuit closes for everyone.
    for _ in range(llm_breaker._failure_threshold):
        llm_breaker.record_failure()
    assert llm_breaker.state == OPEN
    # Fast-forward the real breaker past its cooldown.
    llm_breaker._opened_at -= llm_breaker._cooldown_seconds + 1

    from narration_enrichment.models import TransactionEnrichment

    healthy = TransactionEnrichment(
        merchant="Swiggy", category="food_delivery",
        transaction_type="upi", confidence=0.9,
        human_narration="Food order at Swiggy",
    )
    with patch("narration_enrichment.rag.embed_text", return_value=[0.1] * 8), patch(
        "narration_enrichment.service._call_llm", return_value=healthy
    ):
        r = client.post("/enrich", json={"narration": "UPI/SWIGGY/Payment"})

    assert r.status_code == 200
    assert llm_breaker.state == CLOSED


def test_chat_loop_is_gated_by_the_same_breaker(enrich_harness):
    # Open the shared breaker; a chat message must fail fast with the
    # circuit-open 503 and NEVER construct an LLM call. Proves the
    # shared-fate design: one upstream, one breaker, both routes.
    for _ in range(llm_breaker._failure_threshold):
        llm_breaker.record_failure()

    from narration_enrichment import auth
    from narration_enrichment.db import create_chat_session, insert_api_key

    raw = auth.generate_raw_key()
    db = _TestSessionLocal()
    try:
        insert_api_key(db, key_hash=auth.hash_key(raw), label="breaker-chat")
        create_chat_session(db, session_id="breaker-session", api_key_hash=auth.hash_key(raw))
    finally:
        db.close()

    never_called = MagicMock()
    with patch("narration_enrichment.chat_service.rag.embed_text", return_value=[0.1] * 8), patch(
        "narration_enrichment.chat_service._client.create", never_called
    ):
        r = client.post(
            "/chat/breaker-session/message",
            json={"message": "anything at all"},
            headers={"X-API-Key": raw},
        )

    assert r.status_code == 503
    assert "circuit open" in r.json()["detail"]
    assert never_called.call_count == 0
