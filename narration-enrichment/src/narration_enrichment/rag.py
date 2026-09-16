"""
Week 3 — Retrieval-Augmented Generation.

The problem this solves: Day 2/3 relies entirely on the model's own
training knowledge to classify a merchant. That's fine for household
names (Swiggy, Amazon) but has two real failure modes Phase 1's eval
already surfaced:
  1. Consistency — the same merchant can land in a different category on
     different calls, since nothing forces the model to agree with its
     own past answers.
  2. Local/unusual merchants the model was never trained on well.

The fix doesn't need a vector database or a second LLM provider: this
project already persists every enrichment (Phase 2). That history IS a
knowledge base. This module embeds narrations, stores the embeddings
alongside the row that was already being saved, and retrieves the most
similar past examples to include as few-shot context on the next call —
so the system gets more consistent the more it's used, not because the
model changed, but because it's shown its own past decisions.
"""

import json
import logging
import math

from google.genai.errors import APIError
from sqlalchemy.orm import Session
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from narration_enrichment.config import get_settings
from narration_enrichment.db import EnrichmentRecord, list_records_with_embeddings

logger = logging.getLogger(__name__)

_settings = get_settings()

EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIMENSIONS = 256  # a fraction of the model's full 3072 — plenty
# for short, formulaic bank narrations, and 12x cheaper to store/compare.

TOP_K = 3
# Cosine similarity floor below which a "similar" example is actually just
# noise — including it would make the prompt worse, not better. Chosen by
# eye against real narrations, not derived; worth revisiting once there's
# enough real usage data to tune it properly.
MIN_SIMILARITY = 0.70

_TRANSIENT_CODES = {429, 503, 504}


def _is_transient(exc: BaseException) -> bool:
    # Same check as service.py's _is_transient_provider_error, duplicated
    # rather than imported: embedding calls hit the same transient-error
    # family, but this module has no reason to depend on service.py, and
    # the two retry policies are allowed to diverge later without coupling.
    if isinstance(exc, APIError) and exc.code in _TRANSIENT_CODES:
        return True
    cause = exc.__cause__
    return isinstance(cause, APIError) and cause.code in _TRANSIENT_CODES


@retry(
    retry=retry_if_exception(_is_transient),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
def embed_text(raw_client, text: str, task_type: str) -> list[float]:
    # task_type matters: Gemini's embedding model optimizes DOCUMENT
    # embeddings (what gets stored) differently from QUERY embeddings
    # (what a new narration is embedded as before searching) — this is
    # asymmetric retrieval, not a detail you can skip and still get good
    # similarity scores.
    from google.genai import types

    response = raw_client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=text,
        config=types.EmbedContentConfig(
            output_dimensionality=EMBEDDING_DIMENSIONS,
            task_type=task_type,
        ),
    )
    return response.embeddings[0].values


def cosine_similarity(a: list[float], b: list[float]) -> float:
    # Pure Python on purpose — 256 floats, a few dozen to a few hundred
    # comparisons at this project's scale. Not worth a numpy dependency
    # for one function; would be a different call at real scale.
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def find_similar_examples(
    db: Session, query_embedding: list[float], top_k: int = TOP_K, min_similarity: float = MIN_SIMILARITY
) -> list[EnrichmentRecord]:
    candidates = list_records_with_embeddings(db)
    scored = []
    for record in candidates:
        record_embedding = json.loads(record.embedding)
        similarity = cosine_similarity(query_embedding, record_embedding)
        if similarity >= min_similarity:
            scored.append((similarity, record))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [record for _similarity, record in scored[:top_k]]


def build_context_block(examples: list[EnrichmentRecord]) -> str | None:
    # Cold-start / no-match case: if nothing similar enough exists yet
    # (empty database, or a genuinely novel narration), there is nothing
    # honest to retrieve — fall back to the plain Day 3 prompt rather than
    # forcing in irrelevant examples.
    if not examples:
        return None

    lines = ["Here is how similar past narrations were classified:"]
    for record in examples:
        lines.append(
            f'- "{record.narration}" -> merchant="{record.merchant}", '
            f'category="{record.category}", transaction_type="{record.transaction_type}"'
        )
    lines.append("Use these as guidance for consistency, but judge the new narration on its own merits.")
    return "\n".join(lines)
