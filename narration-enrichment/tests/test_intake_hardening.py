"""
§3-12 Walk 1 (Job A) — dirty-data intake: normalization + in-batch dedup.

The prod-reality questions this answers (interview-prep/README.md):
"customer ka data GANDA aaya to?" — control chars and whitespace shells
are normalized before any validation or spend; and a statement upload
that repeats the same line 12× costs ONE LLM call, not 12.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import narration_enrichment.main as main_module
from narration_enrichment.db import Base, EnrichmentRecord, get_db
from narration_enrichment.main import app, normalize_narration
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


def _result(merchant="Swiggy") -> TransactionEnrichment:
    return TransactionEnrichment(
        merchant=merchant, category="food_delivery", transaction_type="upi",
        confidence=0.9, human_narration=f"Order at {merchant}",
    )


@pytest.fixture(autouse=True)
def _harness(monkeypatch):
    with _test_engine.begin() as conn:
        conn.execute(Base.metadata.tables["enrichment_records"].delete())
        conn.execute(Base.metadata.tables["idempotency_keys"].delete())
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


# --- normalization: the pure function -----------------------------------------


def test_normalization_strips_control_chars_and_collapses_whitespace():
    assert normalize_narration("UPI\x00/SWIGGY\x1f/Payment") == "UPI /SWIGGY /Payment"
    assert normalize_narration("  UPI\t\t/SWIGGY   /Payment \n") == "UPI /SWIGGY /Payment"
    assert normalize_narration("\x00\x01\x02   ") == ""


def test_whitespace_shell_fails_as_422_not_as_a_paid_llm_call():
    # 9 characters of costume, zero characters of narration. Pydantic's
    # min_length must judge the NORMALIZED text (validator mode=before).
    never_called = MagicMock()
    with patch("narration_enrichment.service._call_llm", never_called):
        r = client.post("/enrich", json={"narration": "  \x00\x00 \t  "})

    assert r.status_code == 422
    assert never_called.call_count == 0


def test_normalized_text_is_what_reaches_the_prompt():
    llm = MagicMock(return_value=_result())
    with patch("narration_enrichment.rag.embed_text", return_value=[0.1] * 8), patch(
        "narration_enrichment.service._call_llm", llm
    ):
        r = client.post("/enrich", json={"narration": "UPI\x00/SWIGGY\t\t/Payment "})

    assert r.status_code == 200
    sent_narration = llm.call_args.args[0]
    assert sent_narration == "UPI /SWIGGY /Payment"


# --- in-batch dedup -------------------------------------------------------------


def _batch(narrations):
    return client.post("/enrich/batch", json={"narrations": narrations})


def test_twelve_identical_lines_cost_one_llm_call():
    llm = MagicMock(return_value=_result())
    with patch("narration_enrichment.rag.embed_text", return_value=[0.1] * 8), patch(
        "narration_enrichment.service._call_llm", llm
    ):
        r = _batch(["UPI/SWIGGY/Payment"] * 12)

    assert r.status_code == 200
    body = r.json()
    assert (body["total"], body["succeeded"], body["deduped"]) == (12, 12, 11)
    assert llm.call_count == 1
    # One DB row per unique narration, not one per line.
    db = _TestSessionLocal()
    try:
        assert db.query(EnrichmentRecord).count() == 1
    finally:
        db.close()


def test_dedup_key_is_the_normalized_text():
    # Three spellings of the same line — CSV-export control char, a tab
    # run, trailing spaces — are ONE unit of work.
    llm = MagicMock(return_value=_result())
    with patch("narration_enrichment.rag.embed_text", return_value=[0.1] * 8), patch(
        "narration_enrichment.service._call_llm", llm
    ):
        r = _batch([
            "UPI/SWIGGY/Payment",
            "UPI/SWIGGY/Payment  ",
            "UPI/SWIGGY/Payment\x00",
        ])

    body = r.json()
    assert (body["succeeded"], body["deduped"]) == (3, 2)
    assert llm.call_count == 1
    # The echo stays the client's RAW line — honesty about what was sent.
    assert body["results"][2]["narration"] == "UPI/SWIGGY/Payment\x00"


def test_distinct_narrations_are_not_deduped():
    llm = MagicMock(side_effect=[_result("Swiggy"), _result("Zomato")])
    with patch("narration_enrichment.rag.embed_text", return_value=[0.1] * 8), patch(
        "narration_enrichment.service._call_llm", llm
    ):
        r = _batch(["UPI/SWIGGY/Payment", "UPI/ZOMATO/Payment"])

    body = r.json()
    assert (body["succeeded"], body["deduped"]) == (2, 0)
    assert llm.call_count == 2


def test_duplicate_of_a_failed_item_replicates_the_failure_without_respending():
    # One attempt per unique text per batch — retrying identical bytes
    # in the same request IS the double-spend being prevented. The
    # client retries the whole batch later for a fresh attempt.
    from google.genai.errors import APIError

    llm = MagicMock(side_effect=APIError(code=503, response_json={}, response=None))
    with patch("narration_enrichment.rag.embed_text", return_value=[0.1] * 8), patch(
        "narration_enrichment.service._call_llm", llm
    ):
        r = _batch(["UPI/SWIGGY/Payment", "UPI/SWIGGY/Payment"])

    body = r.json()
    assert (body["failed"], body["deduped"]) == (2, 1)
    assert body["results"][0]["error"] == body["results"][1]["error"]
    assert llm.call_count == 1


def test_empty_after_normalization_item_fails_alone_batch_continues():
    llm = MagicMock(return_value=_result())
    with patch("narration_enrichment.rag.embed_text", return_value=[0.1] * 8), patch(
        "narration_enrichment.service._call_llm", llm
    ):
        r = _batch(["  \x00  ", "UPI/SWIGGY/Payment"])

    body = r.json()
    assert body["results"][0] == {
        **body["results"][0],
        "success": False, "error": "InvalidNarration",
    }
    assert body["results"][1]["success"] is True
    assert (body["succeeded"], body["failed"], body["deduped"]) == (1, 1, 0)
    assert llm.call_count == 1
