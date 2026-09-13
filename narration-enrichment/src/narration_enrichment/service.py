"""
The enrichment pipeline itself. The client is built once at import time
(module-level) and reused for every request — not reconnected per call.
"""

import logging

import instructor
from google import genai
from google.genai import types

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

# Config-driven in spirit even though it's a constant here: this is the one
# place the prompt is defined, not copy-pasted per call site.
PROMPT_TEMPLATE = """Look at this bank transaction narration and tell me the
merchant, the category, the transaction type, and how confident you are.

Narration: {narration}
"""


def enrich_narration(narration: str) -> TransactionEnrichment:
    # DEBUG only: the narration can contain PII (masked card numbers,
    # names). It must never reach INFO-level logs, which is where log
    # aggregation and long retention usually live.
    logger.debug("enrich_narration_raw narration=%r", narration)
    logger.info("enrich_started narration_length=%d", len(narration))

    result = _client.create(
        response_model=TransactionEnrichment,
        messages=[{"role": "user", "content": PROMPT_TEMPLATE.format(narration=narration)}],
        max_retries=_settings.max_retries,
    )

    logger.info(
        "enrich_completed category=%s transaction_type=%s confidence=%.2f",
        result.category,
        result.transaction_type,
        result.confidence,
    )
    return result
