"""
Integration test: the full FastAPI app through its actual HTTP layer
(request validation, routing, exception handling, response serialization)
— but with the LLM call mocked out and the database swapped for an
in-memory SQLite. No network call, no API key needed, no cost, no leftover
.db file on disk, deterministic every run.

This is the same idea as the Java project's @WebMvcTest slice tests: prove
the HTTP contract works without needing the real external dependencies.
"""

from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient
from google.genai.errors import APIError
from instructor.core.exceptions import InstructorRetryException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from narration_enrichment.db import Base, EnrichmentRecord, get_db
from narration_enrichment.main import app
from narration_enrichment.models import TransactionEnrichment

# In-memory, per-test-run database — never touches the real
# narration_enrichment.db file that dev/prod use.
#
# poolclass=StaticPool is not optional here: SQLite's `:memory:` database
# lives inside one connection, and SQLAlchemy's default pool opens a new
# connection per checkout — so create_all() would create the table on
# connection #1, and the app would then query connection #2, which has
# never seen that table ("no such table: enrichment_records"). StaticPool
# forces every checkout through the same single connection.
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


app.dependency_overrides[get_db] = _override_get_db

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean_table():
    # Each test starts from an empty table, even though they share one
    # in-memory engine for the whole test run (creating a fresh engine per
    # test would also work, but this is cheaper and just as isolated).
    with _test_engine.begin() as conn:
        conn.execute(Base.metadata.tables["enrichment_records"].delete())
    yield


FAKE_EMBEDDING = [0.1] * 256


@pytest.fixture(autouse=True)
def _mock_embeddings():
    # Applies to every test in this file, not just the RAG-specific ones —
    # without it, every /enrich or /enrich/batch call would make two real
    # embedding API calls. Patched on the rag MODULE (main.py does
    # `from narration_enrichment import rag`, not `from ...rag import
    # embed_text`), which is exactly the boundary Day 5's notes flagged as
    # the one that actually matters.
    with patch("narration_enrichment.rag.embed_text", return_value=FAKE_EMBEDDING):
        yield


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_enrich_returns_structured_response_when_llm_succeeds():
    fake_result = TransactionEnrichment(
        merchant="Swiggy",
        category="food_delivery",
        transaction_type="UPI",
        confidence=0.95,
    )

    with patch("narration_enrichment.main.enrich_narration", return_value=fake_result):
        response = client.post(
            "/enrich",
            json={"narration": "UPI/P2M/509912345678/PAYTM/SWIGGY BANGALORE/Payment"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["merchant"] == "Swiggy"
    assert body["category"] == "food_delivery"
    assert body["confidence"] == 0.95


def test_enrich_persists_the_result_and_get_enrichments_returns_it():
    fake_result = TransactionEnrichment(
        merchant="Swiggy", category="food_delivery", transaction_type="UPI", confidence=0.95
    )
    with patch("narration_enrichment.main.enrich_narration", return_value=fake_result):
        client.post("/enrich", json={"narration": "UPI/P2M/.../SWIGGY BANGALORE/Payment"})

    response = client.get("/enrichments")
    assert response.status_code == 200
    records = response.json()
    assert len(records) == 1
    assert records[0]["merchant"] == "Swiggy"
    assert "id" in records[0] and "created_at" in records[0]


def test_enrich_rejects_too_short_narration_before_ever_calling_the_llm():
    with patch("narration_enrichment.main.enrich_narration") as mock_enrich:
        response = client.post("/enrich", json={"narration": "ab"})

    assert response.status_code == 422
    # The request never even got as far as the LLM — FastAPI's own
    # request-model validation (min_length=3) short-circuited first.
    mock_enrich.assert_not_called()


def test_enrich_returns_422_when_llm_output_never_validates():
    # No __cause__ set — a genuine shape/validation failure, nothing to do
    # with the provider being unavailable.
    exhausted = InstructorRetryException(
        "model never produced a valid shape after retries",
        n_attempts=3,
        total_usage=None,
    )
    with patch("narration_enrichment.main.enrich_narration", side_effect=exhausted):
        response = client.post(
            "/enrich", json={"narration": "some real-looking narration here"}
        )

    assert response.status_code == 422
    assert "Could not extract" in response.json()["detail"]


def test_enrich_returns_503_when_a_transient_provider_error_exhausts_retries():
    # Week 3 bug: this is the shape .create() ACTUALLY raises when
    # service.py's tenacity retry exhausts on a real 429/503/504 — the
    # original APIError lives in __cause__. Before the fix, this landed
    # in the branch above and returned a misleading 422.
    cause = APIError(503, {"error": {"code": 503, "message": "boom", "status": "UNAVAILABLE"}})
    exhausted = InstructorRetryException("boom", n_attempts=3, total_usage=None)
    exhausted.__cause__ = cause

    with patch("narration_enrichment.main.enrich_narration", side_effect=exhausted):
        response = client.post(
            "/enrich", json={"narration": "some real-looking narration here"}
        )

    assert response.status_code == 503
    assert "temporarily unavailable" in response.json()["detail"]


def test_enrich_returns_504_on_provider_timeout():
    with patch(
        "narration_enrichment.main.enrich_narration",
        side_effect=httpx.ConnectTimeout("timed out"),
    ):
        response = client.post(
            "/enrich", json={"narration": "some real-looking narration here"}
        )

    assert response.status_code == 504


def test_enrich_returns_generic_500_and_never_leaks_the_real_exception_message():
    with patch(
        "narration_enrichment.main.enrich_narration",
        side_effect=RuntimeError("internal detail: db connection string xyz"),
    ):
        response = client.post(
            "/enrich", json={"narration": "some real-looking narration here"}
        )

    assert response.status_code == 500
    assert response.json()["detail"] == "An unexpected error occurred."
    assert "db connection string" not in response.text


def test_batch_rejects_empty_list():
    response = client.post("/enrich/batch", json={"narrations": []})
    assert response.status_code == 422  # min_length=1 on the request model


def test_batch_isolates_a_failing_item_from_the_rest():
    # Item 0 succeeds, item 1 fails outright, item 2 succeeds — proves one
    # bad narration doesn't take down the other 2 in the same batch.
    good = TransactionEnrichment(
        merchant="Swiggy", category="food_delivery", transaction_type="UPI", confidence=0.9
    )
    good2 = TransactionEnrichment(
        merchant="Amazon", category="shopping", transaction_type="POS", confidence=0.9
    )

    with patch(
        "narration_enrichment.main.enrich_narration",
        side_effect=[good, RuntimeError("provider hiccup"), good2],
    ):
        response = client.post(
            "/enrich/batch",
            json={"narrations": ["narration-1", "narration-2", "narration-3"]},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["succeeded"] == 2
    assert body["failed"] == 1
    assert body["results"][0]["success"] is True
    assert body["results"][1]["success"] is False
    assert body["results"][1]["error"] == "RuntimeError"
    assert "provider hiccup" not in response.text  # raw message never leaked
    assert body["results"][2]["success"] is True

    # Both successful items should have been persisted, the failed one not.
    stored = client.get("/enrichments").json()
    assert len(stored) == 2


def test_enrich_calls_llm_with_no_context_when_the_history_is_empty():
    # Cold-start case: nothing in the DB yet, so there is nothing honest
    # to retrieve. enrich_narration must be called with context=None,
    # falling back to exactly Day 3's plain prompt.
    fake_result = TransactionEnrichment(
        merchant="Swiggy", category="food_delivery", transaction_type="UPI", confidence=0.9
    )
    with patch(
        "narration_enrichment.main.enrich_narration", return_value=fake_result
    ) as mock_enrich:
        client.post("/enrich", json={"narration": "UPI/P2M/.../SWIGGY/Payment"})

    mock_enrich.assert_called_once_with("UPI/P2M/.../SWIGGY/Payment", context=None)


def test_enrich_builds_rag_context_from_a_similar_past_record():
    # Seed one prior enrichment whose embedding matches FAKE_EMBEDDING
    # exactly — the mocked embed_text returns that same vector for every
    # call, so cosine similarity is 1.0 and it clears MIN_SIMILARITY.
    import json as _json

    db = _TestSessionLocal()
    db.add(EnrichmentRecord(
        narration="UPI/P2M/OLD/SWIGGY BANGALORE/Payment",
        merchant="Swiggy",
        category="food_delivery",
        transaction_type="UPI",
        confidence=0.9,
        embedding=_json.dumps(FAKE_EMBEDDING),
    ))
    db.commit()
    db.close()

    fake_result = TransactionEnrichment(
        merchant="Swiggy", category="food_delivery", transaction_type="UPI", confidence=0.9
    )
    with patch(
        "narration_enrichment.main.enrich_narration", return_value=fake_result
    ) as mock_enrich:
        client.post("/enrich", json={"narration": "UPI/P2M/NEW/SWIGGY BANGALORE/Payment"})

    _, kwargs = mock_enrich.call_args
    assert kwargs["context"] is not None
    assert "SWIGGY BANGALORE/Payment" in kwargs["context"]
    assert "food_delivery" in kwargs["context"]


def test_enrich_degrades_gracefully_when_embedding_call_fails():
    # RAG is an enhancement, not the critical path. If the embedding call
    # itself is down, /enrich must still succeed — just without context.
    fake_result = TransactionEnrichment(
        merchant="Swiggy", category="food_delivery", transaction_type="UPI", confidence=0.9
    )
    with patch("narration_enrichment.rag.embed_text", side_effect=RuntimeError("embedding API down")):
        with patch(
            "narration_enrichment.main.enrich_narration", return_value=fake_result
        ) as mock_enrich:
            response = client.post("/enrich", json={"narration": "UPI/P2M/.../SWIGGY/Payment"})

    assert response.status_code == 200
    mock_enrich.assert_called_once_with("UPI/P2M/.../SWIGGY/Payment", context=None)

    # The enrichment itself is still persisted, just with no embedding —
    # meaning it won't be retrievable as a future RAG example either, a
    # soft degradation rather than a hard failure.
    stored = client.get("/enrichments").json()
    assert len(stored) == 1
