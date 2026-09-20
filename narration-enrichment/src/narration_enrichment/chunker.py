"""
Chunk a policy document into overlapping text spans for RAG.

Fixed-size + overlap, deliberately boring. The P2 design paper
(`P2_DESIGN.md` §3) picks this over semantic chunking on the same
"smallest infrastructure that satisfies the requirement" rule that kept
this project on SQLite instead of a vector database — if the eval
golden dataset later shows the boring chunker losing classification
accuracy, we'd upgrade with numbers in hand rather than pre-emptively.

The whole module is one pure function: takes `text: str`, returns
`list[Chunk]`. No file I/O, no network, no database. That's the point —
it can be unit-tested with plain string literals and has zero
transaction-boundary interactions, which means the ingest endpoint
(Day 3) can call it inside its DB transaction without worrying about
partial state on an exception.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    """One overlapping span of a source document.

    `index` is the chunk's position in the source (0-based), used
    together with `doc_id` as the stable citation reference: a fresh
    ingest of the same doc produces the same chunk_index for the same
    span. The `content` is the actual substring; the ingest layer
    embeds it and persists both alongside `chunk_index`.
    """

    index: int
    content: str


def chunk(text: str, chunk_size: int = 500, overlap: int = 50) -> list[Chunk]:
    """Split `text` into overlapping fixed-size chunks.

    A rule that straddles two chunks stays retrievable via either one —
    that's what the overlap buys us. Empty or whitespace-only input
    returns an empty list (nothing worth embedding, nothing to store);
    a text shorter than one full chunk becomes a single chunk that
    contains the whole thing (no artificial padding).

    Constraints (deliberately loud, not silently coerced):
    - `chunk_size` must be positive; overlap must be non-negative and
      strictly less than chunk_size, otherwise we'd advance zero or
      negative characters per step and either loop forever or produce
      duplicates. Fail loudly at the boundary rather than surprising
      the caller with a hang or a nonsense result.
    """
    if chunk_size <= 0:
        raise ValueError(f"chunk_size must be positive, got {chunk_size}")
    if overlap < 0:
        raise ValueError(f"overlap must be non-negative, got {overlap}")
    if overlap >= chunk_size:
        # If overlap == chunk_size we'd advance zero chars per step (infinite loop);
        # if overlap > chunk_size the "step" would be negative and every chunk
        # would just re-emit the same span. Both are nonsense.
        raise ValueError(
            f"overlap ({overlap}) must be strictly less than chunk_size ({chunk_size})"
        )

    stripped = text.strip()
    if not stripped:
        return []

    if len(stripped) <= chunk_size:
        return [Chunk(index=0, content=stripped)]

    step = chunk_size - overlap
    chunks: list[Chunk] = []
    idx = 0
    start = 0
    while start < len(stripped):
        end = start + chunk_size
        chunks.append(Chunk(index=idx, content=stripped[start:end]))
        if end >= len(stripped):
            break
        start += step
        idx += 1
    return chunks
