"""
P2 Day 3 — orchestration for ingesting a policy document.

Chunker (Day 2) is a pure function; embed_text (Week 3 RAG) already
exists in `rag.py`; the repository (Day 2) writes atomically. This
module glues them together for one call and one call only:

    ingest(doc_id, title, content) -> IngestResult

Contract:
1. Compute checksum(content). If a doc with this id + this checksum
   already exists, return {unchanged: True} — no embedding budget
   spent, no chunk work redone. This is why callers can safely
   re-run ingest in a CI loop or on every deploy.
2. Chunk the content (pure function, no I/O).
3. Batch-embed every chunk (one loop over `rag.embed_text` with
   `task_type=RETRIEVAL_DOCUMENT` — same asymmetry rule as
   past-narration RAG).
4. Atomic replace via `upsert_policy_doc_with_chunks` — a concurrent
   /enrich either sees the old chunk set or the new, never a
   half-swapped state.

S3 upload of the raw doc is deliberately NOT in this file — that's
Day 4. `source_uri` is passed in by the caller so this module doesn't
own the AWS boundary (which is Rajat's per standing rule 3-2).
Testable in isolation with an in-memory SQLite and a mocked embedding
callable.
"""

import hashlib
import logging
from dataclasses import dataclass
from typing import Callable

from sqlalchemy.orm import Session

from narration_enrichment.chunker import chunk
from narration_enrichment.db import (
    get_policy_doc,
    upsert_policy_doc_with_chunks,
)

logger = logging.getLogger(__name__)


# The embed callable is passed in rather than imported so tests can
# mock the embedding boundary cleanly without any raw_client
# indirection. Signature matches `rag.embed_text(raw_client, text,
# task_type)` for a partial-application-style bind in main.py.
EmbedFn = Callable[[str], list[float]]


@dataclass(frozen=True)
class IngestResult:
    doc_id: str
    chunks_ingested: int
    unchanged: bool
    checksum: str


def compute_checksum(content: str) -> str:
    """SHA-256 of the raw text, hex-encoded.

    Deterministic: same bytes in → same string out. Used to short-
    circuit re-ingest of an unchanged doc without spending embedding
    budget. Public function (not a private helper) because tests use
    it directly and future callers may want to compute a checksum
    without going through the full ingest orchestrator.
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def ingest(
    db: Session,
    *,
    doc_id: str,
    title: str,
    content: str,
    embed_fn: EmbedFn,
    source_uri: str | None = None,
    chunk_size: int = 500,
    overlap: int = 50,
) -> IngestResult:
    """Ingest one policy document.

    Raises `ValueError` on empty content — a doc worth citing has to
    actually contain something. The chunker's own whitespace-strip
    handles leading/trailing space, but a fully empty body is a
    caller bug we should surface, not silently persist as a zero-
    chunk doc that can never be retrieved.
    """
    if not content or not content.strip():
        raise ValueError("policy doc content is empty")

    checksum = compute_checksum(content)

    existing = get_policy_doc(db, doc_id)
    if existing is not None and existing.checksum == checksum:
        # No-op fast path. Do NOT touch ingested_at, source_uri, or
        # anything else — the caller asked to ingest the same bytes;
        # the honest answer is "nothing changed."
        logger.info(
            "policy_ingest_unchanged doc_id=%s checksum=%s", doc_id, checksum[:12]
        )
        return IngestResult(
            doc_id=doc_id,
            chunks_ingested=len(existing.chunks),
            unchanged=True,
            checksum=checksum,
        )

    chunks = chunk(content, chunk_size=chunk_size, overlap=overlap)
    if not chunks:
        # Shouldn't happen (we already rejected empty content above),
        # but the chunker + the "empty" definition could conceivably
        # diverge; belt-and-braces so we never persist a chunk-less
        # doc row that would silently degrade retrieval quality.
        raise ValueError("chunker produced zero chunks — refusing to persist an empty doc")

    # Embedding loop. If any single embedding fails we abort the
    # whole ingest — partial-embed state is worse than no state,
    # because retrieval would find the embedded chunks and miss the
    # rest without any signal that the doc is incomplete.
    embedded: list[tuple[int, str, list[float]]] = []
    for c in chunks:
        vector = embed_fn(c.content)
        embedded.append((c.index, c.content, vector))

    upsert_policy_doc_with_chunks(
        db,
        doc_id=doc_id,
        title=title,
        checksum=checksum,
        source_uri=source_uri,
        chunks=embedded,
    )

    logger.info(
        "policy_ingest_ok doc_id=%s chunks=%d checksum=%s",
        doc_id, len(embedded), checksum[:12],
    )
    return IngestResult(
        doc_id=doc_id,
        chunks_ingested=len(embedded),
        unchanged=False,
        checksum=checksum,
    )
