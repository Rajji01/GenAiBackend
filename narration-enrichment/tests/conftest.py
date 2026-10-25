"""
Suite-wide bootstrap, imported by pytest before any test module.

The suite's contract (README "Test" section) is: no network, no real API
key. But config.Settings requires gemini_api_key, and db.py builds its
engine via get_settings() at import time — so on a machine without a
.env file (fresh clone, CI), collection itself died with a pydantic
ValidationError before any mock or fixture could run. On the original
dev machine a real .env masked this completely.

A placeholder key here keeps the no-key contract actually true on a
clean checkout. Nothing in the suite ever sends it anywhere: the LLM
and embedding boundaries are mocked in every test that reaches them.
setdefault (not assignment) so a developer's real environment, if
present, is left untouched.
"""

import os

os.environ.setdefault("GEMINI_API_KEY", "test-key-never-sent-anywhere")

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_llm_breaker():
    """Hardening H2: the circuit breaker is process-wide shared state
    (by design — one upstream, one breaker). Without this reset, a
    test that drives five provider failures would open the circuit
    for every LATER test in the run, making the suite order-dependent
    — the test-suite version of the exact blast-radius problem the
    breaker exists to contain."""
    from narration_enrichment.circuit_breaker import _reset_for_tests

    _reset_for_tests()
    yield
