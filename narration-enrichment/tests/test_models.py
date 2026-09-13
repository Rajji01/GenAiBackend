"""
Unit tests: no network, no mocking, no FastAPI — just the Pydantic schema's
own validation rules. These are the fastest tests in the project and the
ones that should run on every keystroke.
"""

import pytest
from pydantic import ValidationError

from narration_enrichment.models import TransactionEnrichment


def test_valid_data_constructs_successfully():
    result = TransactionEnrichment(
        merchant="Swiggy",
        category="food_delivery",
        transaction_type="UPI",
        confidence=0.95,
    )
    assert result.merchant == "Swiggy"
    assert result.confidence == 0.95


def test_confidence_above_one_is_rejected():
    with pytest.raises(ValidationError):
        TransactionEnrichment(
            merchant="Swiggy",
            category="food_delivery",
            transaction_type="UPI",
            confidence=1.5,
        )


def test_confidence_below_zero_is_rejected():
    with pytest.raises(ValidationError):
        TransactionEnrichment(
            merchant="Swiggy",
            category="food_delivery",
            transaction_type="UPI",
            confidence=-0.1,
        )


def test_category_outside_the_allowed_set_is_rejected():
    with pytest.raises(ValidationError):
        TransactionEnrichment(
            merchant="Swiggy",
            category="not_a_real_category",
            transaction_type="UPI",
            confidence=0.9,
        )


def test_confidence_as_a_word_is_rejected():
    # This is exactly the Day 2 failure mode we saw live:
    # {"confidence": "High"}. The schema is what stops it from ever
    # reaching a caller, regardless of which LLM produced it.
    with pytest.raises(ValidationError):
        TransactionEnrichment(
            merchant="Swiggy",
            category="food_delivery",
            transaction_type="UPI",
            confidence="High",
        )
