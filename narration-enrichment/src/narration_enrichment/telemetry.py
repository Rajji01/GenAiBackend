"""
P7 Day 3 — LLM call telemetry: cost/latency as first-class rows.

You cannot route on cost/latency you don't measure (P7_DESIGN.md §3).
Every LLM call on every surface becomes an `llm_calls` row — surface,
model, latency, outcome, tokens, estimated cost — written by the call
wrapper ITSELF, non-fatally, through its own short session: a
telemetry hiccup must never fail the user's request (the run_eval
persistence precedent, P3 invariant #4).

Token truth, by surface (one honest deviation from the design paper,
recorded here and in its §3): REAL `usage_metadata` tokens ride the
ENRICH surface via `create_with_completion`. Chat/dispute surfaces
record latency+outcome with tokens None THIS arc — their mock seam is
`_client.create` across ~40 existing tests, and reshaping that seam
for token counts is a follow-up (instructor's hooks API is the clean
path), not a smuggle. None, never a fake 0 — the /stats rule.

The daily budget is OBSERVE-AND-SHOUT: crossing it flips
`/ops/llm.budget.exceeded` and logs `llm_budget_exceeded` (the line an
operator pages on). It never blocks calls — blocking on spend is the
rate limiter's job, on a signal it can actually trust.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# USD per 1M tokens (input, output). AN ESTIMATE for budget math, not
# billing: provider prices drift and this table WILL go stale — the
# est_cost_usd column name says "est" for exactly that reason. Update
# alongside model changes; an unknown model estimates None, never 0.
PRICE_TABLE: dict[str, tuple[float, float]] = {
    "gemini-3.6-flash": (0.30, 2.50),
}

OUTCOME_OK = "ok"
OUTCOME_PROVIDER_DOWN = "provider_down"
OUTCOME_ERROR = "error"


def extract_usage(completion) -> tuple[int | None, int | None]:
    """Defensive read of google-genai's usage_metadata off the raw
    completion `create_with_completion` returns. Any missing attribute
    → (None, None): an SDK reshape must degrade telemetry, never break
    the call path."""
    meta = getattr(completion, "usage_metadata", None)
    if meta is None:
        return None, None
    prompt = getattr(meta, "prompt_token_count", None)
    out = getattr(meta, "candidates_token_count", None)
    return (
        int(prompt) if isinstance(prompt, (int, float)) else None,
        int(out) if isinstance(out, (int, float)) else None,
    )


def estimate_cost(model: str, prompt_tokens: int | None, completion_tokens: int | None) -> float | None:
    if prompt_tokens is None or completion_tokens is None:
        return None
    prices = PRICE_TABLE.get(model)
    if prices is None:
        return None
    in_price, out_price = prices
    return (prompt_tokens * in_price + completion_tokens * out_price) / 1_000_000


class _Recorder:
    """What the `record` context manager hands to its body: a place to
    attach the raw completion when the surface has one."""

    def __init__(self) -> None:
        self.prompt_tokens: int | None = None
        self.completion_tokens: int | None = None

    def set_usage_from(self, completion) -> None:
        self.prompt_tokens, self.completion_tokens = extract_usage(completion)


@contextmanager
def record(surface: str, model: str):
    """Wrap exactly one provider call attempt. Each tenacity retry
    attempt is its own wrapped call and its own row — a wire call is a
    wire call, and the rows are how you SEE the retries."""
    rec = _Recorder()
    started = time.monotonic()
    outcome = OUTCOME_OK
    try:
        yield rec
    except Exception as exc:
        # Same judgement the breaker uses — one vocabulary for
        # "the provider was down" across the whole codebase.
        from narration_enrichment.service import counts_as_provider_down

        outcome = OUTCOME_PROVIDER_DOWN if counts_as_provider_down(exc) else OUTCOME_ERROR
        raise
    finally:
        latency_ms = int((time.monotonic() - started) * 1000)
        _write_row(surface, model, latency_ms, outcome, rec)


def _write_row(surface: str, model: str, latency_ms: int, outcome: str, rec: _Recorder) -> None:
    try:
        # Deferred imports + own short session: telemetry must not
        # participate in (or poison) the caller's transaction.
        from narration_enrichment.config import get_settings
        from narration_enrichment.db import (
            LlmCall,
            SessionLocal,
            sum_llm_cost_today,
        )

        cost = estimate_cost(model, rec.prompt_tokens, rec.completion_tokens)
        db = SessionLocal()
        try:
            db.add(LlmCall(
                surface=surface,
                model=model,
                latency_ms=latency_ms,
                outcome=outcome,
                prompt_tokens=rec.prompt_tokens,
                completion_tokens=rec.completion_tokens,
                est_cost_usd=cost,
            ))
            db.commit()

            if cost is not None:
                spent = sum_llm_cost_today(db)
                budget = get_settings().llm_daily_budget_usd
                if spent > budget:
                    # The shout. Logged on every over-budget priced
                    # call on purpose: an operator greps for the LAST
                    # occurrence, and silence-after-first would read
                    # as recovery.
                    logger.warning(
                        "llm_budget_exceeded spent_est_usd=%.4f daily_budget_usd=%.4f",
                        spent, budget,
                    )
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 - observability never fails the op
        logger.warning("llm_telemetry_write_failed error=%s", exc)
