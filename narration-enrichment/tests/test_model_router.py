"""
P7 Day 4 — model routing + the fallback chain.

The two load-bearing claims under test:
- IDENTITY: under default config the router resolves to THE existing
  `service._client` object — which is why ~40 existing mock-seam tests
  kept passing untouched when routing was wired in.
- THE NARROW TRIGGER: the fallback fires only when the primary attempt
  exhausts as provider-down; a caller error doesn't consult it, and an
  OPEN circuit never reaches the chain at all.
"""

from unittest.mock import MagicMock, patch

import pytest

from narration_enrichment import config, model_router, service
from narration_enrichment.circuit_breaker import CLOSED, CircuitOpenError, llm_breaker
from narration_enrichment.models import TransactionEnrichment
from narration_enrichment.service import enrich_narration


@pytest.fixture(autouse=True)
def _fresh_router(monkeypatch):
    config.get_settings.cache_clear()
    model_router._reset_for_tests()
    yield
    config.get_settings.cache_clear()
    model_router._reset_for_tests()


def _result() -> TransactionEnrichment:
    return TransactionEnrichment(
        merchant="Swiggy", category="food_delivery", transaction_type="upi",
        confidence=0.9, human_narration="Food order at Swiggy",
    )


# --- routing is data ------------------------------------------------------------


def test_model_for_defaults_to_the_single_configured_model():
    default = config.get_settings().model_name
    assert model_router.model_for("enrich") == default
    assert model_router.model_for("chat") == default
    assert model_router.model_for("dispute_judge") == default


def test_per_surface_override_is_an_env_change_not_a_diff(monkeypatch):
    monkeypatch.setenv("MODEL_CHAT", "gemini-bigger")
    config.get_settings.cache_clear()

    assert model_router.model_for("chat") == "gemini-bigger"
    assert model_router.model_for("enrich") == config.get_settings().model_name


def test_default_client_is_service_client_by_identity():
    # The claim that kept every existing mock seam alive: all names
    # resolve to ONE object under default config.
    assert model_router.client_for(config.get_settings().model_name) is service._client


def test_non_default_client_is_built_once_and_cached(monkeypatch):
    c1 = model_router.client_for("gemini-sibling")
    c2 = model_router.client_for("gemini-sibling")

    assert c1 is c2
    assert c1 is not service._client


# --- the chain -------------------------------------------------------------------


def test_chain_is_primary_only_without_fallback():
    assert model_router.chain_for("enrich") == [config.get_settings().model_name]


def test_chain_appends_fallback_and_drops_it_when_it_is_the_primary(monkeypatch):
    monkeypatch.setenv("FALLBACK_MODEL", "gemini-sibling")
    config.get_settings.cache_clear()
    assert model_router.chain_for("enrich") == [config.get_settings().model_name, "gemini-sibling"]

    monkeypatch.setenv("FALLBACK_MODEL", config.get_settings().model_name)
    config.get_settings.cache_clear()
    # Retrying the SAME model twice is tenacity's job, already done.
    assert model_router.chain_for("enrich") == [config.get_settings().model_name]


# --- the narrow trigger, end to end -----------------------------------------------


def _wire(primary_effect, fallback_effect):
    """Patch _call_llm to behave per-model: the chain calls it with
    model=..., so the fake dispatches on that."""
    primary = config.get_settings().model_name

    def _dispatch(narration, context, policy_context, model=None):
        effect = primary_effect if model == primary else fallback_effect
        if isinstance(effect, Exception):
            raise effect
        return effect

    return patch("narration_enrichment.service._call_llm", side_effect=_dispatch)


def test_provider_down_primary_falls_back_once_and_heals_the_breaker(monkeypatch):
    from google.genai.errors import APIError

    monkeypatch.setenv("FALLBACK_MODEL", "gemini-sibling")
    config.get_settings.cache_clear()

    with _wire(
        primary_effect=APIError(code=503, response_json={}, response=None),
        fallback_effect=_result(),
    ):
        result = enrich_narration("UPI/SWIGGY/Payment")

    assert result.merchant == "Swiggy"
    # The fallback SUCCESS recorded breaker-success — the provider
    # demonstrably answered; one primary failure never accumulates
    # toward OPEN across a healthy fallback.
    assert llm_breaker.state == CLOSED


def test_caller_error_on_primary_never_consults_the_fallback(monkeypatch):
    monkeypatch.setenv("FALLBACK_MODEL", "gemini-sibling")
    config.get_settings.cache_clear()

    calls: list[str] = []

    def _dispatch(narration, context, policy_context, model=None):
        calls.append(model)
        raise ValueError("caller bug — same bytes will fail on any model")

    with patch("narration_enrichment.service._call_llm", side_effect=_dispatch):
        with pytest.raises(ValueError):
            enrich_narration("UPI/SWIGGY/Payment")

    assert calls == [config.get_settings().model_name]  # fallback untouched


def test_fallback_also_down_propagates_the_original_error_shape(monkeypatch):
    from google.genai.errors import APIError

    monkeypatch.setenv("FALLBACK_MODEL", "gemini-sibling")
    config.get_settings.cache_clear()

    with _wire(
        primary_effect=APIError(code=503, response_json={}, response=None),
        fallback_effect=APIError(code=503, response_json={}, response=None),
    ):
        with pytest.raises(APIError):
            enrich_narration("UPI/SWIGGY/Payment")


def test_open_circuit_never_consults_the_fallback(monkeypatch):
    monkeypatch.setenv("FALLBACK_MODEL", "gemini-sibling")
    config.get_settings.cache_clear()
    for _ in range(llm_breaker._failure_threshold):
        llm_breaker.record_failure()

    never_called = MagicMock()
    with patch("narration_enrichment.service._call_llm", never_called):
        with pytest.raises(CircuitOpenError):
            enrich_narration("UPI/SWIGGY/Payment")

    # Same provider, same fate: the breaker's gate sits BEFORE the
    # chain — a sibling-model retry during an outage is a retry storm
    # in a costume.
    assert never_called.call_count == 0
