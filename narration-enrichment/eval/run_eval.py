"""
Week 2, Phase 1 — Evaluation & Golden Dataset.

Day 5's tests proved the PIPELINE works (mocked LLM, checks shape/status
codes). This script proves the OUTPUT is actually correct — it makes real
calls to Gemini against a hand-labeled dataset and checks whether the
extracted fields match what a human would expect.

This is deliberately NOT a pytest test: it costs real money and quota on
every run, takes real time, and an LLM's answer can legitimately vary run
to run. Run it manually whenever you change the prompt, the schema, or the
model. The comparison logic itself (compare_result) is a pure function and
IS covered by a real pytest test in tests/test_eval_logic.py — that part
has no excuse to be untested just because the LLM call next to it does.

Run: uv run python eval/run_eval.py
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from narration_enrichment.models import TransactionEnrichment  # noqa: E402
from narration_enrichment.service import enrich_narration  # noqa: E402

DATASET_PATH = Path(__file__).parent / "golden_dataset.json"
RESULTS_DIR = Path(__file__).parent / "results"

# The free tier caps gemini-3.6-flash at 5 requests/minute AND 20/day
# (found the hard way — see Week 2 notes). This delay keeps single eval
# runs under the per-minute cap; the per-day cap has no code-level fix,
# only "don't run this more than a couple of times a day."
RATE_LIMIT_DELAY_SECONDS = 13


def compare_result(case: dict, result: TransactionEnrichment) -> dict:
    """Pure comparison logic — no network call, fully unit-testable."""
    merchant_ok = case["expected_merchant_contains"].lower() in result.merchant.lower()
    category_ok = result.category == case["expected_category"]
    type_ok = result.transaction_type.upper() == case["expected_transaction_type"].upper()

    return {
        "id": case["id"],
        "narration": case["narration"],
        "got": {
            "merchant": result.merchant,
            "category": result.category,
            "transaction_type": result.transaction_type,
            "confidence": result.confidence,
        },
        "expected": {
            "merchant_contains": case["expected_merchant_contains"],
            "category": case["expected_category"],
            "transaction_type": case["expected_transaction_type"],
        },
        "checks": {
            "merchant": merchant_ok,
            "category": category_ok,
            "transaction_type": type_ok,
        },
        "all_correct": merchant_ok and category_ok and type_ok,
    }


def check_one(case: dict) -> dict:
    result = enrich_narration(case["narration"])
    return compare_result(case, result)


def main() -> None:
    dataset = json.loads(DATASET_PATH.read_text())
    outcomes = []

    print(f"Running eval against {len(dataset)} golden examples...\n")

    for i, case in enumerate(dataset):
        if i > 0:
            time.sleep(RATE_LIMIT_DELAY_SECONDS)
        try:
            outcome = check_one(case)
        except Exception as exc:
            # A failed CALL (timeout, quota, provider outage) is a
            # reliability finding, not a correctness finding — kept
            # separate from the accuracy numbers below on purpose.
            outcome = {
                "id": case["id"],
                "narration": case["narration"],
                "error": f"{type(exc).__name__}: {exc}",
                "call_failed": True,
                "all_correct": False,
                "checks": {"merchant": False, "category": False, "transaction_type": False},
            }
        outcomes.append(outcome)

        status = "PASS" if outcome["all_correct"] else "FAIL"
        print(f"[{status}] {case['id']:<24} {case['narration'][:50]}")
        if status == "FAIL":
            if "error" in outcome:
                print(f"       error: {outcome['error']}")
            else:
                for field, ok in outcome["checks"].items():
                    if not ok:
                        print(f"       {field}: expected~{outcome['expected']}, got={outcome['got']}")

    total = len(outcomes)
    completed = [o for o in outcomes if not o.get("call_failed")]
    field_names = ["merchant", "category", "transaction_type"]

    call_failure_rate = (total - len(completed)) / total

    print("\n--- Summary ---")
    print(f"{'calls completed':<28} {len(completed)}/{total}")
    print(f"{'call failure rate':<28} {call_failure_rate:.0%}  (reliability, not correctness — timeouts/quota/outages)")

    if completed:
        for field in field_names:
            acc = sum(1 for o in completed if o["checks"][field]) / len(completed)
            print(f"{'accuracy: ' + field:<28} {acc:.0%}  (of calls that completed)")
        overall_accuracy = sum(1 for o in completed if o["all_correct"]) / len(completed)
        print(f"{'accuracy: all fields':<28} {overall_accuracy:.0%}  (of calls that completed)")
        other_bucket_rate = sum(1 for o in completed if o["got"]["category"] == "other") / len(completed)
        print(f"{'other-category rate':<28} {other_bucket_rate:.0%}  (diagnostic: is the schema's category set too narrow?)")
    else:
        print("No calls completed — nothing to measure accuracy on.")

    RESULTS_DIR.mkdir(exist_ok=True)
    report_path = RESULTS_DIR / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    report_path.write_text(json.dumps({"total": total, "completed": len(completed), "outcomes": outcomes}, indent=2))
    print(f"\nFull report saved to {report_path}")


if __name__ == "__main__":
    main()
