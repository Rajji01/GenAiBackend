"""
The enrichment pipeline itself. The client is built once at import time
(module-level) and reused for every request — not reconnected per call.
"""

import logging
import time

import httpx
import instructor
from google import genai
from google.genai import types
from google.genai.errors import APIError
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from narration_enrichment.circuit_breaker import llm_breaker
from narration_enrichment.config import get_settings
from narration_enrichment.models import TransactionEnrichment

logger = logging.getLogger(__name__)

_settings = get_settings()

_raw_client = genai.Client(
    api_key=_settings.gemini_api_key,
    # Bounded so a slow/unreachable provider can never hang a request
    # forever — this is the "latency budget" the caller is protected by.
    http_options=types.HttpOptions(timeout=int(_settings.request_timeout_seconds * 1000)),
)
_client = instructor.from_genai(_raw_client, model=_settings.model_name)


def get_raw_client():
    # rag.py needs the raw (non-Instructor-wrapped) client for embedding
    # calls — embed_content isn't a structured-output call Instructor has
    # any role in, so it goes straight to the same underlying client
    # service.py already built, rather than constructing a second one.
    return _raw_client


# Config-driven in spirit even though it's a constant here: this is the one
# place the prompt is defined, not copy-pasted per call site.
#
# Two optional context blocks land here between the task description and
# the narration itself:
#   - {past_block}   — Week 3 RAG, past classifications ("evidence")
#   - {policy_block} — P2 RAG, applicable policy excerpts ("rules")
# Rendered blank when None, so the plain Day-3 prompt is still the
# fallback shape when neither retrieval finds anything.
PROMPT_TEMPLATE = """Look at this bank transaction narration and tell me the
merchant, the category, the transaction type, and how confident you are.
{past_block}{policy_block}
Narration: {narration}
"""

# Found live, Week 2: the free tier throws 429 (quota), 503 (overloaded)
# and 504 (deadline) — none of which Instructor retries itself (it only
# retries ValidationError/JSONDecodeError, see Day 3 notes). Those three
# are the ONLY codes retried here — a real 400 (bad request) or 404 (bad
# model name) retrying would just waste three attempts failing the same
# way three times.
_TRANSIENT_CODES = {429, 503, 504}


def counts_as_provider_down(exc: BaseException) -> bool:
    """Hardening H2 — the breaker's failure signal. Strictly the
    transient whitelist PLUS timeouts (gray failure: a provider that
    is not down, just uselessly slow, is down for our purposes once
    it does this consistently). Anything else — a 400, a validation
    error — means the provider ANSWERED, which is evidence of life,
    not death; the caller records that as breaker-success even while
    re-raising the error to its own caller. Public (no underscore)
    because chat_service shares the exact same judgement."""
    if isinstance(exc, httpx.TimeoutException) or isinstance(
        exc.__cause__, httpx.TimeoutException
    ):
        return True
    return _is_transient_provider_error(exc)


def _is_transient_provider_error(exc: BaseException) -> bool:
    # Found live, Week 3: Instructor's OWN internal retry_sync_v2 catches
    # every exception from the underlying API call — including ones that
    # were never actually shape-retried — and re-raises it wrapped as
    # InstructorRetryException(...) from original_error. So .create()
    # never raises a raw APIError; it always raises InstructorRetryException
    # with the real APIError sitting in __cause__. Checking only
    # isinstance(exc, APIError) here looked correct and passed every test,
    # but never once matched a real failure — this transient-retry logic
    # was dead code until this second check was added.
    if isinstance(exc, APIError) and exc.code in _TRANSIENT_CODES:
        return True
    cause = exc.__cause__
    return isinstance(cause, APIError) and cause.code in _TRANSIENT_CODES


@retry(
    retry=retry_if_exception(_is_transient_provider_error),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
def _call_llm(
    narration: str,
    context: str | None,
    policy_context: str | None,
    model: str | None = None,
) -> TransactionEnrichment:
    # This is a SEPARATE retry layer from Instructor's own max_retries
    # below — that one retries a bad SHAPE by re-asking the model; this
    # one retries a failed CALL because the provider itself was briefly
    # unavailable. Conflating the two into one retry loop would mean a
    # shape problem and a quota problem both looked the same from the
    # outside, which they aren't and shouldn't be handled the same way.
    past_block = f"\n{context}\n" if context else ""
    # P2 Day 5: policy block sits AFTER the past block. Order matters
    # only lightly — the labels distinguish evidence from rules — but
    # anchoring the policy nearer the narration reads slightly better
    # in practice (recent-primacy bias of the model itself).
    policy_block = f"\n{policy_context}\n" if policy_context else ""
    prompt = PROMPT_TEMPLATE.format(
        narration=narration,
        past_block=past_block,
        policy_block=policy_block,
    )
    # P7 Day 3 — every wire attempt is a telemetry row; this surface
    # gets REAL token counts via create_with_completion (the raw
    # completion carries usage_metadata; mocks without it degrade to
    # tokens=None, never fake 0). P7 Day 4: the client is resolved by
    # the router — identical object to _client under default config,
    # a cached sibling when MODEL_ENRICH/FALLBACK_MODEL route away.
    from narration_enrichment import model_router, telemetry

    model = model or model_router.model_for("enrich")
    client = model_router.client_for(model)
    with telemetry.record("enrich", model) as rec:
        result, completion = client.create_with_completion(
            response_model=TransactionEnrichment,
            messages=[{"role": "user", "content": prompt}],
            max_retries=_settings.max_retries,
        )
        rec.set_usage_from(completion)
    return result


def enrich_narration(
    narration: str,
    context: str | None = None,
    policy_context: str | None = None,
) -> TransactionEnrichment:
    # `context` is Week 3's RAG hook (past classifications, "evidence").
    # `policy_context` is P2's hook (applicable policy chunks, "rules").
    # Either or both may be None — a `None` context means "no similar-
    # enough history yet" / "no matching policy yet"; the prompt block
    # is simply omitted, and the model behaves exactly as it did before
    # the corresponding retrieval was added. Degrade-not-fail.
    #
    # DEBUG only: the narration can contain PII (masked card numbers,
    # names). It must never reach INFO-level logs, which is where log
    # aggregation and long retention usually live.
    logger.debug("enrich_narration_raw narration=%r", narration)
    logger.info(
        "enrich_started narration_length=%d rag_context_used=%s policy_context_used=%s",
        len(narration),
        context is not None,
        policy_context is not None,
    )

    # Hardening H2 — the breaker gates the call BEFORE any provider
    # work: while OPEN this raises CircuitOpenError in microseconds
    # (no thread held for 20s, no quota spent, no retry storm into a
    # dead upstream). Note the rate limiter was already acquired by
    # the caller at this point — an OPEN circuit still consumed a
    # quota slot; acceptable, because while the provider is down the
    # quota is worthless anyway, and re-ordering would couple the two
    # mechanisms the design keeps separate.
    llm_breaker.allow()

    # P7 Day 4 — the fallback chain. [primary] in default config (the
    # loop degenerates to exactly the old wiring); [primary, fallback]
    # when FALLBACK_MODEL is set. The breaker gate above runs ONCE,
    # before the chain: an OPEN circuit never consults the fallback —
    # same provider, same fate (P7_DESIGN §4).
    from narration_enrichment import model_router

    chain = model_router.chain_for("enrich")
    started_at = time.monotonic()
    result = None
    for position, routed_model in enumerate(chain):
        try:
            result = _call_llm(narration, context, policy_context, model=routed_model)
        except Exception as exc:
            down = counts_as_provider_down(exc)
            if down:
                llm_breaker.record_failure()
            else:
                # The provider responded — unhappily, but it's alive.
                llm_breaker.record_success()
            if down and position == 0 and len(chain) > 1:
                logger.warning(
                    "llm_fallback_attempt from=%s to=%s", routed_model, chain[1]
                )
                continue
            raise
        # A success anywhere in the chain is provider-alive evidence.
        llm_breaker.record_success()
        break
    latency_ms = (time.monotonic() - started_at) * 1000

    logger.info(
        "enrich_completed category=%s transaction_type=%s confidence=%.2f latency_ms=%.0f",
        result.category,
        result.transaction_type,
        result.confidence,
        latency_ms,
    )
    return result
