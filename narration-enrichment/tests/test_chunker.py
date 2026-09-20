"""
Unit tests for chunker.py. Pure function, no fixtures needed beyond
plain strings — the whole point of Day 2's shape decision.

The interesting cases here are the ones that would silently produce
nonsense in the field: empty input, one-chunk input shorter than
chunk_size, and the bad-parameter combinations that would hang or
duplicate.
"""

import pytest

from narration_enrichment.chunker import Chunk, chunk


def test_empty_string_returns_empty_list():
    assert chunk("") == []


def test_whitespace_only_input_returns_empty_list():
    # Nothing worth embedding, nothing to store — this is the "clean
    # input handled cleanly" boundary rather than a validation error,
    # because a Markdown doc with a trailing blank line shouldn't fail.
    assert chunk("   \n\n\t") == []


def test_short_input_returns_single_chunk_at_index_zero():
    result = chunk("hello world", chunk_size=100, overlap=10)

    assert result == [Chunk(index=0, content="hello world")]


def test_input_leading_and_trailing_whitespace_is_trimmed():
    # The chunker owns the "strip once at the boundary" concern — the
    # ingest layer shouldn't have to remember to strip separately.
    result = chunk("   hello   ", chunk_size=100, overlap=10)

    assert result == [Chunk(index=0, content="hello")]


def test_long_input_produces_overlapping_chunks_with_correct_indexes():
    text = "abcdefghij"  # 10 chars

    result = chunk(text, chunk_size=4, overlap=1)

    # step = 4 - 1 = 3. Starts: 0, 3, 6. Ends: 4, 7, 10 → stop
    # (end >= len). No spurious tail chunk is emitted for the "start=9"
    # slot — that behavior is deliberate: a tiny orphan chunk would
    # just be a shorter copy of the previous chunk's tail via overlap,
    # not new information worth its own embedding.
    assert [c.content for c in result] == ["abcd", "defg", "ghij"]
    assert [c.index for c in result] == [0, 1, 2]


def test_long_input_zero_overlap_covers_the_tail_with_a_partial_chunk():
    # With overlap=0 the last chunk may legitimately be shorter — no
    # earlier chunk covers those tail characters, so we do emit it.
    # 11 chars, chunk_size=4, overlap=0 → "abcd", "efgh", "ijk".
    result = chunk("abcdefghijk", chunk_size=4, overlap=0)

    assert [c.content for c in result] == ["abcd", "efgh", "ijk"]
    assert [c.index for c in result] == [0, 1, 2]


def test_overlap_zero_produces_disjoint_chunks():
    text = "abcdefghij"  # 10 chars

    result = chunk(text, chunk_size=5, overlap=0)

    assert [c.content for c in result] == ["abcde", "fghij"]


def test_chunk_boundary_that_lands_exactly_on_end_stops_cleanly():
    # 6 chars, chunk_size 3, overlap 0 → two chunks that fit exactly.
    # The stop condition mustn't emit a spurious empty final chunk.
    result = chunk("abcdef", chunk_size=3, overlap=0)

    assert result == [Chunk(0, "abc"), Chunk(1, "def")]


def test_chunk_size_zero_raises():
    with pytest.raises(ValueError, match="chunk_size must be positive"):
        chunk("hello", chunk_size=0, overlap=0)


def test_chunk_size_negative_raises():
    with pytest.raises(ValueError, match="chunk_size must be positive"):
        chunk("hello", chunk_size=-5, overlap=0)


def test_overlap_negative_raises():
    with pytest.raises(ValueError, match="overlap must be non-negative"):
        chunk("hello", chunk_size=10, overlap=-1)


def test_overlap_equal_to_chunk_size_raises():
    # Would advance zero chars per step → infinite loop. Fail loudly.
    with pytest.raises(ValueError, match="strictly less than chunk_size"):
        chunk("hello world", chunk_size=5, overlap=5)


def test_overlap_greater_than_chunk_size_raises():
    with pytest.raises(ValueError, match="strictly less than chunk_size"):
        chunk("hello world", chunk_size=5, overlap=10)


def test_chunks_are_immutable_dataclasses():
    # frozen=True — a chunk once created is a value, not a container.
    # This matters because the ingest layer builds a list of chunks
    # BEFORE calling embed, and we don't want a later step accidentally
    # rewriting a chunk's content in place after it's been embedded.
    c = Chunk(index=0, content="hello")
    with pytest.raises((AttributeError, Exception)):
        c.content = "world"  # type: ignore[misc]
