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
from narration_enrichment.db import (
    EnrichmentRecord,
    PolicyChunk,
    list_policy_chunks_with_embeddings,
    list_records_with_embeddings,
)

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

# P2 Day 5 — policy-chunk retrieval floor is a shade lower than the past-
# narration floor. Policy excerpts are shorter and more abstract, so the
# cosine score is inherently a bit lower even when a chunk is clearly
# relevant. Revisit alongside MIN_SIMILARITY once the Day-6 eval extension
# gives us numbers to tune with.
POLICY_MIN_SIMILARITY = 0.65
POLICY_TOP_K = 3

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


# ---------------------------------------------------------------------------
# P2 Day 5 — policy-chunk retrieval (parallel to past-narration retrieval)
# ---------------------------------------------------------------------------


def retrieve_policy_chunks(
    db: Session,
    query_embedding: list[float],
    top_k: int = POLICY_TOP_K,
    min_similarity: float = POLICY_MIN_SIMILARITY,
) -> list[tuple[float, PolicyChunk]]:
    """Top-K policy chunks above the similarity floor for this narration.

    Returns (score, chunk) tuples so the caller can:
    1. label them by similarity in the prompt if it wants, and
    2. populate `policy_citations` on the response with the exact
       score at retrieval time — that's what makes citations
       *earned*, not decorative (P2_DESIGN §6).

    Same shape as `find_similar_examples` for past narrations, so
    the read path across both stores stays symmetric. Note: NO
    embedding call happens here — the caller passes in an already-
    embedded query so one narration only pays for one embedding
    call regardless of how many retrieval targets are searched.
    """
    candidates = list_policy_chunks_with_embeddings(db)
    scored: list[tuple[float, PolicyChunk]] = []
    for chunk in candidates:
        chunk_embedding = json.loads(chunk.embedding)
        similarity = cosine_similarity(query_embedding, chunk_embedding)
        if similarity >= min_similarity:
            scored.append((similarity, chunk))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return scored[:top_k]


def build_policy_context_block(
    scored_chunks: list[tuple[float, PolicyChunk]],
) -> str | None:
    """Format policy chunks into a labeled prompt block.

    Deliberately distinct label from the past-narration block —
    prompt-engineering-wise these are different signals: past
    narrations are *evidence*, policy chunks are *rules*. The model
    should treat a policy override as authoritative and past
    classifications as guidance. Making the labels different is one
    lever we have to nudge that.
    """
    if not scored_chunks:
        return None

    lines = ["Applicable policy excerpts from trusted policy docs:"]
    for _score, chunk in scored_chunks:
        lines.append(
            f'- [doc_id={chunk.doc_id}, chunk {chunk.chunk_index}]: "{chunk.content}"'
        )
    lines.append(
        "Treat these as rules, not just suggestions — if a policy applies, prefer it over your default classification."
    )
    return "\n".join(lines)
