"""
P7 Day 3 — LLM telemetry: every call a row, the budget that shouts.

The telemetry writer uses its OWN short session (db.SessionLocal) so a
hiccup never poisons the caller's transaction — tests therefore patch
`narration_enrichment.db.SessionLocal` to point at the test engine,
which is itself part of the contract under test (the deferred-import
seam exists exactly so this redirection works).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from google.genai.errors import APIError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import narration_enrichment.main as main_module
from narration_enrichment import auth, telemetry
from narration_enrichment.db import Base, LlmCall, get_db, insert_api_key
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
RAW_KEY = "telemetry-test-key"


@pytest.fixture(autouse=True)
def _harness(monkeypatch):
    with _test_engine.begin() as conn:
        conn.execute(Base.metadata.tables["llm_calls"].delete())
        conn.execute(Base.metadata.tables["enrichment_records"].delete())
        conn.execute(Base.metadata.tables["api_keys"].delete())
    db = _TestSessionLocal()
    try:
        insert_api_key(db, key_hash=auth.hash_key(RAW_KEY), label="telemetry-tests")
    finally:
        db.close()
    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _override_get_db
    monkeypatch.setattr(main_module, "rate_limiter", RateLimiter(per_minute=1000, per_day=10000))
    # Redirect the writer's own session to the test engine.
    monkeypatch.setattr("narration_enrichment.db.SessionLocal", _TestSessionLocal)
    try:
        yield
    finally:
        if previous is not None:
            app.dependency_overrides[get_db] = previous
        else:
            app.dependency_overrides.pop(get_db, None)


def _rows():
    db = _TestSessionLocal()
    try:
        return db.query(LlmCall).order_by(LlmCall.id.asc()).all()
    finally:
        db.close()


def _fake_completion(prompt=120, out=45):
    return SimpleNamespace(usage_metadata=SimpleNamespace(
        prompt_token_count=prompt, candidates_token_count=out,
    ))


# --- the pure pieces -----------------------------------------------------------


def test_extract_usage_reads_real_metadata_and_degrades_to_none():
    assert telemetry.extract_usage(_fake_completion(100, 50)) == (100, 50)
    assert telemetry.extract_usage(SimpleNamespace()) == (None, None)
    assert telemetry.extract_usage(SimpleNamespace(usage_metadata=SimpleNamespace())) == (None, None)


def test_estimate_cost_is_none_for_unknown_model_or_missing_tokens():
    assert telemetry.estimate_cost("gemini-3.6-flash", 1_000_000, 1_000_000) == pytest.approx(0.30 + 2.50)
    assert telemetry.estimate_cost("some-unknown-model", 100, 100) is None
    assert telemetry.estimate_cost("gemini-3.6-flash", None, 50) is None


# --- the recorder --------------------------------------------------------------


def test_success_writes_an_ok_row_with_usage():
    with telemetry.record("enrich", "gemini-3.6-flash") as rec:
        rec.set_usage_from(_fake_completion(200, 80))

    rows = _rows()
    assert len(rows) == 1
    row = rows[0]
    assert (row.surface, row.model, row.outcome) == ("enrich", "gemini-3.6-flash", "ok")
    assert (row.prompt_tokens, row.completion_tokens) == (200, 80)
    assert row.est_cost_usd == pytest.approx((200 * 0.30 + 80 * 2.50) / 1e6)
    assert row.latency_ms >= 0


def test_provider_down_and_caller_error_are_distinct_outcomes():
    with pytest.raises(APIError):
        with telemetry.record("chat", "gemini-3.6-flash"):
            raise APIError(code=503, response_json={}, response=None)
    with pytest.raises(ValueError):
        with telemetry.record("chat", "gemini-3.6-flash"):
            raise ValueError("caller bug")

    outcomes = [r.outcome for r in _rows()]
    assert outcomes == ["provider_down", "error"]
    # Failed calls carry no usage → tokens/cost None, never fake 0.
    assert all(r.est_cost_usd is None for r in _rows())


def test_telemetry_write_failure_never_fails_the_call(monkeypatch):
    monkeypatch.setattr(
        "narration_enrichment.db.SessionLocal",
        MagicMock(side_effect=RuntimeError("telemetry db gone")),
    )
    with telemetry.record("enrich", "gemini-3.6-flash"):
        pass  # the wrapped call succeeded; the WRITE will fail silently

    # No exception above = the contract. (And obviously no row.)


def test_budget_shout_logs_when_estimated_spend_crosses_the_line(monkeypatch, caplog):
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "0.0000001")
    from narration_enrichment import config
    config.get_settings.cache_clear()
    try:
        import logging
        with caplog.at_level(logging.WARNING, logger="narration_enrichment.telemetry"):
            with telemetry.record("enrich", "gemini-3.6-flash") as rec:
                rec.set_usage_from(_fake_completion(1000, 1000))
        assert any("llm_budget_exceeded" in m for m in caplog.messages)
    finally:
        config.get_settings.cache_clear()


# --- the enrich surface end-to-end ----------------------------------------------


def test_enrich_records_real_usage_through_create_with_completion():
    result = TransactionEnrichment(
        merchant="Swiggy", category="food_delivery", transaction_type="upi",
        confidence=0.9, human_narration="Food order at Swiggy",
    )
    with patch("narration_enrichment.rag.embed_text", return_value=[0.1] * 8), patch(
        "narration_enrichment.service._client.create_with_completion",
        return_value=(result, _fake_completion(300, 60)),
    ):
        r = client.post("/enrich", json={"narration": "UPI/SWIGGY/Payment"})

    assert r.status_code == 200
    rows = [r_ for r_ in _rows() if r_.surface == "enrich"]
    assert len(rows) == 1
    assert rows[0].prompt_tokens == 300
    assert rows[0].est_cost_usd is not None


# --- /ops/llm --------------------------------------------------------------------


def test_ops_llm_requires_auth_and_rolls_up_per_surface():
    assert client.get("/ops/llm").status_code == 401

    with telemetry.record("enrich", "gemini-3.6-flash") as rec:
        rec.set_usage_from(_fake_completion(100, 10))
    with telemetry.record("enrich", "gemini-3.6-flash") as rec:
        rec.set_usage_from(_fake_completion(300, 30))
    with pytest.raises(APIError):
        with telemetry.record("chat", "gemini-3.6-flash"):
            raise APIError(code=503, response_json={}, response=None)

    r = client.get("/ops/llm", headers={"X-API-Key": RAW_KEY})

    assert r.status_code == 200
    body = r.json()
    enrich = body["surfaces"]["enrich"]
    assert (enrich["calls"], enrich["ok"]) == (2, 2)
    assert enrich["prompt_tokens"] == 400
    assert enrich["p50_latency_ms"] is not None
    chat = body["surfaces"]["chat"]
    assert (chat["calls"], chat["provider_down"]) == (1, 1)
    # Chat carried no usage → None (unknown), never 0.
    assert chat["prompt_tokens"] is None
    assert body["budget"]["exceeded"] is False
    assert body["budget"]["spent_est_usd"] > 0
