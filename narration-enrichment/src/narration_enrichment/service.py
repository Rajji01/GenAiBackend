"""
The enrichment pipeline itself. The client is built once at import time
(module-level) and reused for every request — not reconnected per call.
"""

import logging
import time

import instructor
from google import genai
from google.genai import types
from google.genai.errors import APIError
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

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
PROMPT_TEMPLATE = """Look at this bank transaction narration and tell me the
merchant, the category, the transaction type, and how confident you are.
{context_block}
Narration: {narration}
"""

# Found live, Week 2: the free tier throws 429 (quota), 503 (overloaded)
# and 504 (deadline) — none of which Instructor retries itself (it only
# retries ValidationError/JSONDecodeError, see Day 3 notes). Those three
# are the ONLY codes retried here — a real 400 (bad request) or 404 (bad
# model name) retrying would just waste three attempts failing the same
# way three times.
_TRANSIENT_CODES = {429, 503, 504}


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
def _call_llm(narration: str, context: str | None) -> TransactionEnrichment:
    # This is a SEPARATE retry layer from Instructor's own max_retries
    # below — that one retries a bad SHAPE by re-asking the model; this
    # one retries a failed CALL because the provider itself was briefly
    # unavailable. Conflating the two into one retry loop would mean a
    # shape problem and a quota problem both looked the same from the
    # outside, which they aren't and shouldn't be handled the same way.
    context_block = f"\n{context}\n" if context else ""
    prompt = PROMPT_TEMPLATE.format(narration=narration, context_block=context_block)
    return _client.create(
        response_model=TransactionEnrichment,
        messages=[{"role": "user", "content": prompt}],
        max_retries=_settings.max_retries,
    )


def enrich_narration(narration: str, context: str | None = None) -> TransactionEnrichment:
    # `context` is Week 3's RAG hook: rag.py retrieves similar past
    # narrations and formats them into this string. None (the default)
    # means "no similar-enough history yet" — falls back to exactly Day
    # 3's plain prompt, unchanged.
    #
    # DEBUG only: the narration can contain PII (masked card numbers,
    # names). It must never reach INFO-level logs, which is where log
    # aggregation and long retention usually live.
    logger.debug("enrich_narration_raw narration=%r", narration)
    logger.info(
        "enrich_started narration_length=%d rag_context_used=%s",
        len(narration),
        context is not None,
    )

    started_at = time.monotonic()
    result = _call_llm(narration, context)
    latency_ms = (time.monotonic() - started_at) * 1000

    logger.info(
        "enrich_completed category=%s transaction_type=%s confidence=%.2f latency_ms=%.0f",
        result.category,
        result.transaction_type,
        result.confidence,
        latency_ms,
    )
    return result
