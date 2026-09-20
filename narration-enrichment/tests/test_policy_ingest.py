"""
Unit tests for policy_ingest.py.

The embedding boundary is mocked (a plain lambda counting calls) —
that's the only external dependency this orchestrator has, and it's
already the same seam integration tests will use in main.py's
policy route. The DB is real (in-memory SQLite + StaticPool + FK
enforcement on), same fixture shape as tests/test_db.py.
"""

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from narration_enrichment.db import Base, PolicyChunk, PolicyDoc
from narration_enrichment.policy_ingest import compute_checksum, ingest


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


class _CountingEmbedder:
    """Simple stand-in for rag.embed_text — returns a deterministic
    per-input vector and counts total calls, so tests can assert on
    "we didn't embed again" behavior directly."""

    def __init__(self):
        self.calls = 0

    def __call__(self, text: str) -> list[float]:
        self.calls += 1
        # Deterministic embedding from a hash — not a real vector,
        # but consistent enough to be assertable if a test wants to.
        return [(ord(c) % 7) / 7.0 for c in text[:3].ljust(3, "x")]


def test_ingest_stores_doc_and_chunks(db_session):
    embed = _CountingEmbedder()

    result = ingest(
        db_session,
        doc_id="merchant_map",
        title="Merchant map v1",
        content="A" * 1200,     # 1200 chars → 3 chunks at default 500/50
        embed_fn=embed,
    )

    assert result.unchanged is False
    assert result.chunks_ingested == 3
    assert embed.calls == 3     # one embed per chunk

    doc = db_session.query(PolicyDoc).filter(PolicyDoc.doc_id == "merchant_map").one()
    assert doc.title == "Merchant map v1"
    assert doc.checksum == result.checksum
    chunks = db_session.query(PolicyChunk).filter(PolicyChunk.doc_id == "merchant_map").all()
    assert len(chunks) == 3
    assert [c.chunk_index for c in chunks] == [0, 1, 2]


def test_reingest_same_content_is_noop(db_session):
    embed = _CountingEmbedder()
    content = "Merchant: SWIGGY -> food_delivery. Merchant: OLA -> transport."

    first = ingest(db_session, doc_id="d1", title="v1", content=content, embed_fn=embed)
    assert first.unchanged is False
    assert embed.calls == 1

    second = ingest(db_session, doc_id="d1", title="v1", content=content, embed_fn=embed)

    # Same checksum, so the fast-path returns unchanged=True and does
    # NOT re-embed anything — this is the whole point of storing the
    # checksum on the doc row.
    assert second.unchanged is True
    assert second.chunks_ingested == 1
    assert embed.calls == 1     # unchanged from the first ingest


def test_reingest_with_changed_content_replaces_chunks(db_session):
    embed = _CountingEmbedder()

    ingest(db_session, doc_id="d1", title="v1", content="A" * 700, embed_fn=embed)   # 2 chunks
    calls_after_v1 = embed.calls

    result = ingest(db_session, doc_id="d1", title="v2", content="B" * 300, embed_fn=embed)  # 1 chunk

    assert result.unchanged is False
    assert result.chunks_ingested == 1
    chunks = db_session.query(PolicyChunk).filter(PolicyChunk.doc_id == "d1").all()
    # Old chunks gone (atomic replace via upsert); new set is the
    # single chunk from v2. If the replace weren't atomic, we might
    # see the v1 chunks lingering here.
    assert len(chunks) == 1
    assert chunks[0].content.startswith("B")
    # And re-embedding did happen because the checksum changed.
    assert embed.calls == calls_after_v1 + 1


def test_ingest_updates_title_on_content_change(db_session):
    embed = _CountingEmbedder()
    ingest(db_session, doc_id="d1", title="old title", content="one", embed_fn=embed)
    ingest(db_session, doc_id="d1", title="new title", content="two", embed_fn=embed)

    doc = db_session.query(PolicyDoc).filter(PolicyDoc.doc_id == "d1").one()
    assert doc.title == "new title"


def test_ingest_rejects_empty_content(db_session):
    embed = _CountingEmbedder()
    with pytest.raises(ValueError, match="empty"):
        ingest(db_session, doc_id="d1", title="t", content="", embed_fn=embed)
    with pytest.raises(ValueError, match="empty"):
        ingest(db_session, doc_id="d1", title="t", content="   \n\n", embed_fn=embed)
    # No side effect from the rejected calls.
    assert embed.calls == 0
    assert db_session.query(PolicyDoc).count() == 0


def test_ingest_aborts_and_persists_nothing_when_embed_fails_midway(db_session):
    # Simulates a transient provider failure on the 2nd chunk after
    # the 1st was embedded successfully. Contract: no partial-embed
    # state — the DB is untouched, the caller sees the raw exception
    # and can decide (retry / alert / etc.).
    class _FailingOnCallN:
        def __init__(self, fail_on: int):
            self.calls = 0
            self.fail_on = fail_on

        def __call__(self, text: str) -> list[float]:
            self.calls += 1
            if self.calls == self.fail_on:
                raise RuntimeError("simulated embed failure")
            return [0.1, 0.2, 0.3]

    embed = _FailingOnCallN(fail_on=2)

    with pytest.raises(RuntimeError, match="simulated embed failure"):
        ingest(db_session, doc_id="d1", title="t", content="A" * 1200, embed_fn=embed)

    # 1200 chars produces 3 chunks; call 2 raised → nothing persisted.
    assert db_session.query(PolicyDoc).count() == 0
    assert db_session.query(PolicyChunk).count() == 0


def test_compute_checksum_is_deterministic_and_content_sensitive():
    a = compute_checksum("hello")
    b = compute_checksum("hello")
    c = compute_checksum("hello ")   # trailing space differs

    assert a == b
    assert a != c


def test_ingest_records_source_uri_when_provided(db_session):
    embed = _CountingEmbedder()
    ingest(
        db_session,
        doc_id="d1", title="t", content="hello",
        embed_fn=embed,
        source_uri="s3://bucket/policy-docs/d1.md",
    )

    doc = db_session.query(PolicyDoc).filter(PolicyDoc.doc_id == "d1").one()
    assert doc.source_uri == "s3://bucket/policy-docs/d1.md"
