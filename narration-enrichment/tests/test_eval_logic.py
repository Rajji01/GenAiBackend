"""
Unit tests for the eval script's own comparison logic (eval/run_eval.py's
compare_result). The logic that decides pass/fail needs to be correct just
as much as any other code — and unlike the eval script itself, this part
costs nothing to test, so it belongs in the normal suite, not skipped just
because the LLM call sitting next to it is expensive.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "eval"))

from run_eval import compare_result  # noqa: E402

from narration_enrichment.models import TransactionEnrichment


def _case(**overrides):
    base = {
        "id": "test",
        "narration": "irrelevant for this test",
        "expected_merchant_contains": "swiggy",
        "expected_category": "food_delivery",
        "expected_transaction_type": "UPI",
    }
    base.update(overrides)
    return base


def test_exact_match_passes():
    result = TransactionEnrichment(
        merchant="Swiggy", category="food_delivery", transaction_type="UPI", confidence=0.9
    )
    outcome = compare_result(_case(), result)
    assert outcome["all_correct"] is True


def test_merchant_match_is_case_insensitive_substring():
    # Real models say "SWIGGY BANGALORE", "Swiggy", "swiggy.com" — an exact
    # match would fail all three even though a human would call them correct.
    result = TransactionEnrichment(
        merchant="SWIGGY BANGALORE", category="food_delivery", transaction_type="UPI", confidence=0.9
    )
    outcome = compare_result(_case(), result)
    assert outcome["checks"]["merchant"] is True


def test_wrong_category_fails_only_that_field():
    result = TransactionEnrichment(
        merchant="Swiggy", category="shopping", transaction_type="UPI", confidence=0.9
    )
    outcome = compare_result(_case(), result)
    assert outcome["checks"]["category"] is False
    assert outcome["checks"]["merchant"] is True
    assert outcome["all_correct"] is False


def test_transaction_type_comparison_is_case_insensitive():
    result = TransactionEnrichment(
        merchant="Swiggy", category="food_delivery", transaction_type="upi", confidence=0.9
    )
    outcome = compare_result(_case(), result)
    assert outcome["checks"]["transaction_type"] is True


def test_wrong_merchant_fails():
    result = TransactionEnrichment(
        merchant="Amazon", category="food_delivery", transaction_type="UPI", confidence=0.9
    )
    outcome = compare_result(_case(), result)
    assert outcome["checks"]["merchant"] is False
