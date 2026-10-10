"""
P6 Day 5 — the dispute-agent eval: agent run + LLM-as-judge + threshold gate.

Like run_eval.py this costs REAL quota on every case (agent loop calls
+ one judge call per case) — manual trigger only, never CI-automatic.
Unlike run_eval.py there is no exact-match comparison: the judge grades
each ResolutionProposal against the golden rubric, the code cross-checks
the objective field, and the THRESHOLD GATE decides the exit code —
non-zero means "do not ship this prompt/model change."

Run: uv run python eval/run_eval_disputes.py
Exit codes: 0 = gate passed; 1 = gate failed; numbers printed either way.
"""

import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from narration_enrichment import auth  # noqa: E402

DATASET_PATH = Path(__file__).parent / "golden_disputes.json"
RESULTS_DIR = Path(__file__).parent / "results"

# Same free-tier pacing discipline as run_eval.py. A dispute case can
# spend several LLM calls (loop steps + judge), so the sleep sits
# between CASES, and the per-case call count is reported so a quota
# budget can be planned before running all 8.
RATE_LIMIT_DELAY_SECONDS = 13


def run_one_case(db, case: dict) -> dict:
    """Seed the case's evidence → create + run the dispute → judge it.
    Returns an outcome dict shaped for record_eval_run (the same
    contract run_eval.py's outcomes use)."""
    from narration_enrichment.db import (
        Dispute, EnrichmentRecord, create_dispute, list_agent_steps,
    )
    from narration_enrichment.dispute_agent import ResolutionProposal, run_dispute_agent
    from narration_enrichment.dispute_judge import judge_proposal

    # Seed this case's evidence rows (isolated DB per run — see main()).
    seeded_ids = []
    for row in case["seed_enrichments"]:
        rec = EnrichmentRecord(
            narration=row["narration"], merchant=row["merchant"],
            category=row["category"], transaction_type=row["transaction_type"],
            confidence=0.9,
        )
        db.add(rec)
        db.commit()
        db.refresh(rec)
        seeded_ids.append(rec.id)

    disputed_id = (
        seeded_ids[case["disputed_index"]]
        if case.get("disputed_index") is not None and seeded_ids
        else None
    )

    kh = auth.hash_key(auth.generate_raw_key())
    from narration_enrichment.db import insert_api_key
    insert_api_key(db, key_hash=kh, label=f"eval-{case['id']}")
    dispute_id = str(uuid.uuid4())
    create_dispute(db, dispute_id=dispute_id, api_key_hash=kh,
                   enrichment_id=disputed_id, claim_text=case["claim_text"])

    started = time.monotonic()
    dispute = run_dispute_agent(db, dispute_id=dispute_id)      # REAL agent loop
    agent_ms = int((time.monotonic() - started) * 1000)

    trail = [
        f"step {s.step_index}: {s.action}"
        + (f" {s.tool_name}" if s.tool_name else "")
        + (f" → {s.observation}" if s.observation else "")
        for s in list_agent_steps(db, dispute_id=dispute_id)
    ]

    if dispute.status != "PROPOSED":
        # ESCALATED counts as correct ONLY when the golden resolution
        # is needs_human — otherwise it's a miss. Judged without an
        # LLM call (nothing to grade).
        escalation_ok = case["expected_resolution"] == "needs_human"
        return {
            "id": case["id"],
            "narration": case["claim_text"],
            "expected": {"class": case["expected_class"], "resolution": case["expected_resolution"]},
            "got": {"status": dispute.status, "reason": dispute.escalation_reason},
            "checks": {"escalation_acceptable": escalation_ok},
            "all_correct": escalation_ok,
            "latency_ms": agent_ms,
            "verdict": None,
        }

    proposal = ResolutionProposal.model_validate_json(dispute.proposal_json)
    verdict = judge_proposal(case, proposal, trail)              # REAL judge call

    resolution_ok = proposal.resolution == case["expected_resolution"]
    all_ok = verdict.classification_correct and resolution_ok and verdict.grounded >= 1
    return {
        "id": case["id"],
        "narration": case["claim_text"],
        "expected": {"class": case["expected_class"], "resolution": case["expected_resolution"]},
        "got": {
            "class": proposal.dispute_class, "resolution": proposal.resolution,
            "explanation": proposal.explanation,
            "grounded": verdict.grounded, "policy_compliant": verdict.policy_compliant,
            "judge_reasoning": verdict.reasoning,
        },
        "checks": {
            "classification": verdict.classification_correct,
            "resolution": resolution_ok,
            "grounded_at_least_1": verdict.grounded >= 1,
        },
        "all_correct": all_ok,
        "latency_ms": agent_ms,
        "verdict": verdict,
    }


def main() -> int:
    # Isolated on-disk eval DB so eval runs never pollute the dev DB's
    # enrichments/disputes (and the dev DB's rows never leak into the
    # agent's evidence tools mid-eval).
    import os
    eval_db_path = Path(__file__).parent / "results" / "disputes_eval.db"
    eval_db_path.parent.mkdir(exist_ok=True)
    if eval_db_path.exists():
        eval_db_path.unlink()
    os.environ["DATABASE_URL"] = f"sqlite:///{eval_db_path}"

    from narration_enrichment.config import get_settings
    get_settings.cache_clear()

    from narration_enrichment.db import SessionLocal, record_eval_run
    from narration_enrichment.dispute_judge import (
        JUDGE_RUBRIC_VERSION, threshold_gate,
    )

    cases = json.loads(DATASET_PATH.read_text())
    outcomes, verdicts = [], []
    started_at = datetime.now(timezone.utc)
    print(f"Running dispute eval against {len(cases)} golden cases "
          f"(rubric {JUDGE_RUBRIC_VERSION})...\n")

    db = SessionLocal()
    try:
        for i, case in enumerate(cases):
            if i > 0:
                time.sleep(RATE_LIMIT_DELAY_SECONDS)
            try:
                outcome = run_one_case(db, case)
            except Exception as exc:  # noqa: BLE001 — reliability bucket, not correctness
                outcome = {
                    "id": case["id"], "narration": case["claim_text"],
                    "expected": {}, "got": {},
                    "error": f"{type(exc).__name__}: {exc}",
                    "all_correct": False, "checks": {},
                    "latency_ms": None, "verdict": None,
                }
            if outcome.get("verdict") is not None:
                verdicts.append(outcome["verdict"])
                outcome["got"] = dict(outcome["got"])  # keep JSON-serializable
            outcome.pop("verdict", None)
            outcomes.append(outcome)
            print(f"[{'PASS' if outcome['all_correct'] else 'FAIL'}] {case['id']:<28} "
                  f"{case['claim_text'][:48]}")

        finished_at = datetime.now(timezone.utc)
        passed_gate, metrics = threshold_gate(verdicts)

        print("\n--- Gate ---")
        for k, v in metrics.items():
            print(f"{k:<28} {v}")
        print(f"{'GATE':<28} {'PASSED' if passed_gate else 'FAILED'}")

        RESULTS_DIR.mkdir(exist_ok=True)
        report_path = RESULTS_DIR / f"disputes_{finished_at.strftime('%Y%m%dT%H%M%SZ')}.json"
        report_path.write_text(json.dumps(
            {"outcomes": outcomes, "gate": metrics, "gate_passed": passed_gate}, indent=2,
        ))
        print(f"\nReport: {report_path}")

        settings = get_settings()
        try:
            record_eval_run(
                db,
                run_id=str(uuid.uuid4()),
                started_at=started_at,
                finished_at=finished_at,
                model_name=settings.model_name,
                outcomes=outcomes,
                notes=f"dispute-eval {JUDGE_RUBRIC_VERSION} gate={'pass' if passed_gate else 'FAIL'}",
            )
            print("Persisted to eval_runs/eval_results.")
        except Exception as exc:  # noqa: BLE001 — persistence never blocks the verdict
            print(f"[eval-history] persistence failed (report still written): {exc}",
                  file=sys.stderr)

        return 0 if passed_gate else 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
