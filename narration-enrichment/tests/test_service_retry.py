"""
Unit tests for the transient-error retry-with-backoff added in Week 2,
Phase 3 — directly motivated by real 429/503/504 responses hit while
running the eval script (see eval/results and Week 2 notes).

IMPORTANT shape note (Week 3 bug, fixed here): mocking `_client.create`
to raise a raw APIError does NOT reproduce what actually happens live.
Instructor's own retry_sync_v2 catches every exception from the
underlying call and re-raises it as `InstructorRetryException(...) from
original_error` — so `.create()` never raises a bare APIError; the real
APIError sits in `.__cause__`. The first version of this test file mocked
a raw APIError, passed 9/9, and the retry logic it was "testing" had
never once fired in production. These tests now raise the same wrapped
shape a real failure actually has.

No network call: the Gemini client's .create() is mocked at the
boundary, and tenacity's real backoff/stop logic runs for real against
those mocks.
"""

from unittest.mock import patch

import pytest
from google.genai.errors import APIError
from instructor.core.exceptions import InstructorRetryException

from narration_enrichment.models import TransactionEnrichment
from narration_enrichment.service import _is_transient_provider_error, enrich_narration


def _api_error(code: int, status: str) -> APIError:
    return APIError(code, {"error": {"code": code, "message": "boom", "status": status}})


def _wrapped_transient(code: int, status: str) -> InstructorRetryException:
    """What .create() actually raises in real life for a transient failure."""
    cause = _api_error(code, status)
    wrapped = InstructorRetryException(str(cause), n_attempts=1, total_usage=None)
    wrapped.__cause__ = cause
    return wrapped


@pytest.mark.parametrize("code", [429, 503, 504])
def test_transient_codes_are_recognized_via_the_wrapped_exception(code):
    # This is the shape .create() actually raises — see module docstring.
    assert _is_transient_provider_error(_wrapped_transient(code, "X")) is True


@pytest.mark.parametrize("code", [400, 401, 404])
def test_non_transient_codes_are_not_retried(code):
    # A bad request or bad model name will fail identically on every
    # attempt — retrying it three times just makes the caller wait longer
    # for the exact same failure.
    assert _is_transient_provider_error(_wrapped_transient(code, "X")) is False


def test_raw_apierror_is_still_recognized_directly():
    # Belt-and-suspenders: if some future Instructor version ever DOES
    # let a raw APIError through unwrapped, it must still be caught.
    assert _is_transient_provider_error(_api_error(503, "UNAVAILABLE")) is True


def test_recovers_after_transient_errors_within_the_retry_budget():
    good_result = TransactionEnrichment(
        merchant="Swiggy", category="food_delivery", transaction_type="UPI", confidence=0.9
    )
    # Fails twice with the real wrapped shape, then succeeds on the 3rd
    # try — exactly stop_after_attempt(3)'s budget, no more.
    with patch(
        "narration_enrichment.service._client.create",
        side_effect=[
            _wrapped_transient(503, "UNAVAILABLE"),
            _wrapped_transient(429, "RESOURCE_EXHAUSTED"),
            good_result,
        ],
    ):
        import tenacity

        with patch.object(tenacity.nap.time, "sleep", return_value=None):
            result = enrich_narration("some narration")

    assert result.merchant == "Swiggy"


def test_gives_up_after_exhausting_the_retry_budget():
    with patch(
        "narration_enrichment.service._client.create",
        side_effect=_wrapped_transient(503, "UNAVAILABLE"),  # every attempt fails the same way
    ):
        import tenacity

        with patch.object(tenacity.nap.time, "sleep", return_value=None):
            with pytest.raises(InstructorRetryException):
                enrich_narration("some narration")


def test_non_transient_error_is_not_retried_at_all():
    call_count = 0

    def _raise_once(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise _wrapped_transient(400, "INVALID_ARGUMENT")

    with patch("narration_enrichment.service._client.create", side_effect=_raise_once):
        with pytest.raises(InstructorRetryException):
            enrich_narration("some narration")

    assert call_count == 1  # no retry attempted for a non-transient error
