"""
Unit tests for the transient-error retry-with-backoff added in Week 2,
Phase 3 — directly motivated by real 429/503/504 responses hit while
running the eval script (see eval/results and Week 2 notes). No network
call: the Gemini client's .create() is mocked at the boundary, and
tenacity's real backoff/stop logic runs for real against those mocks.
"""

from unittest.mock import patch

import pytest
from google.genai.errors import APIError

from narration_enrichment.models import TransactionEnrichment
from narration_enrichment.service import _is_transient_provider_error, enrich_narration


def _api_error(code: int, status: str) -> APIError:
    return APIError(code, {"error": {"code": code, "message": "boom", "status": status}})


@pytest.mark.parametrize("code", [429, 503, 504])
def test_transient_codes_are_recognized(code):
    assert _is_transient_provider_error(_api_error(code, "X")) is True


@pytest.mark.parametrize("code", [400, 401, 404])
def test_non_transient_codes_are_not_retried(code):
    # A bad request or bad model name will fail identically on every
    # attempt — retrying it three times just makes the caller wait longer
    # for the exact same failure.
    assert _is_transient_provider_error(_api_error(code, "X")) is False


def test_recovers_after_transient_errors_within_the_retry_budget():
    good_result = TransactionEnrichment(
        merchant="Swiggy", category="food_delivery", transaction_type="UPI", confidence=0.9
    )
    # Fails twice with a transient error, then succeeds on the 3rd try —
    # exactly stop_after_attempt(3)'s budget, no more.
    with patch(
        "narration_enrichment.service._client.create",
        side_effect=[_api_error(503, "UNAVAILABLE"), _api_error(429, "RESOURCE_EXHAUSTED"), good_result],
    ):
        with patch("narration_enrichment.service.time.sleep", return_value=None):
            # tenacity's wait_exponential really sleeps between attempts;
            # this test isn't about timing, so the sleep itself is muted —
            # what matters is that all 3 attempts happen and the 3rd wins.
            import tenacity

            with patch.object(tenacity.nap.time, "sleep", return_value=None):
                result = enrich_narration("some narration")

    assert result.merchant == "Swiggy"


def test_gives_up_after_exhausting_the_retry_budget():
    with patch(
        "narration_enrichment.service._client.create",
        side_effect=_api_error(503, "UNAVAILABLE"),  # every attempt fails the same way
    ):
        import tenacity

        with patch.object(tenacity.nap.time, "sleep", return_value=None):
            with pytest.raises(APIError):
                enrich_narration("some narration")


def test_non_transient_error_is_not_retried_at_all():
    call_count = 0

    def _raise_once(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise _api_error(400, "INVALID_ARGUMENT")

    with patch("narration_enrichment.service._client.create", side_effect=_raise_once):
        with pytest.raises(APIError):
            enrich_narration("some narration")

    assert call_count == 1  # no retry attempted for a non-transient error
