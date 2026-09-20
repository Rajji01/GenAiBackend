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
import uuid
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
    started_at = time.monotonic()
    result = enrich_narration(case["narration"])
    latency_ms = int((time.monotonic() - started_at) * 1000)
    outcome = compare_result(case, result)
    outcome["latency_ms"] = latency_ms
    return outcome


def _persist_run_to_db(outcomes: list[dict], started_at: datetime, finished_at: datetime,
                       model_name: str, notes: str | None = None) -> str | None:
    """P3 Day 5: write the run + per-case outcomes to eval_runs +
    eval_results alongside the existing JSON report. Wrapped in
    try/except so a DB-side failure never blocks the eval itself —
    the JSON file is still the source of truth for one-off checks,
    the DB is the "how has case X trended" observability layer.

    Returns the run_id on success, None on failure. Prints the
    failure message to stderr so a broken DB path shows up without
    causing the eval script itself to exit non-zero.
    """
    try:
        # Deferred import so `--help` and the pure-compare tests
        # don't need a DB engine.
        from narration_enrichment.db import SessionLocal, record_eval_run
    except Exception as exc:      # noqa: BLE001
        print(f"[eval-history] DB layer unavailable, skipping persistence: {exc}", file=sys.stderr)
        return None

    run_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        record_eval_run(
            db,
            run_id=run_id,
            started_at=started_at,
            finished_at=finished_at,
            model_name=model_name,
            outcomes=outcomes,
            notes=notes,
        )
        return run_id
    except Exception as exc:      # noqa: BLE001
        print(f"[eval-history] persistence failed, JSON report still written: {exc}", file=sys.stderr)
        return None
    finally:
        db.close()


def main() -> None:
    dataset = json.loads(DATASET_PATH.read_text())
    outcomes = []
    started_at = datetime.now(timezone.utc)

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

    finished_at = datetime.now(timezone.utc)

    RESULTS_DIR.mkdir(exist_ok=True)
    report_path = RESULTS_DIR / f"{finished_at.strftime('%Y%m%dT%H%M%SZ')}.json"
    report_path.write_text(json.dumps({"total": total, "completed": len(completed), "outcomes": outcomes}, indent=2))
    print(f"\nFull report saved to {report_path}")

    # P3 Day 5: also persist to eval_runs + eval_results so
    # GET /eval/history can surface trends. Non-fatal on failure —
    # the JSON file above is unchanged and remains the primary
    # artifact.
    from narration_enrichment.config import get_settings  # deferred, same reason
    settings = get_settings()
    run_id = _persist_run_to_db(
        outcomes=outcomes,
        started_at=started_at,
        finished_at=finished_at,
        model_name=settings.model_name,
    )
    if run_id:
        print(f"Eval run persisted to DB with run_id={run_id}")


if __name__ == "__main__":
    main()
