"""
Integration test: the full FastAPI app through its actual HTTP layer
(request validation, routing, exception handling, response serialization)
— but with the LLM call mocked out. No network call, no API key needed,
no cost, deterministic every run.

This is the same idea as the Java project's @WebMvcTest slice tests: prove
the HTTP contract works without needing the real external dependency.
"""

from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from instructor.core.exceptions import InstructorRetryException

from narration_enrichment.main import app
from narration_enrichment.models import TransactionEnrichment

client = TestClient(app)


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


def test_enrich_rejects_too_short_narration_before_ever_calling_the_llm():
    with patch("narration_enrichment.main.enrich_narration") as mock_enrich:
        response = client.post("/enrich", json={"narration": "ab"})

    assert response.status_code == 422
    # The request never even got as far as the LLM — FastAPI's own
    # request-model validation (min_length=3) short-circuited first.
    mock_enrich.assert_not_called()


def test_enrich_returns_422_when_llm_output_never_validates():
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
