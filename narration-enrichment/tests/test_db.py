"""
Unit tests for db.py's aggregation functions (Week 4's /stats) AND the
P2 policy-doc repository — against a real in-memory SQLite, because
the behavior under test IS SQL semantics (GROUP BY, AVG, cascade
delete, unique constraint) and mocking those away would test the mock,
not the code.
"""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from narration_enrichment.db import (
    Base,
    EnrichmentRecord,
    PolicyChunk,
    PolicyDoc,
    delete_policy_doc,
    get_category_counts,
    get_policy_doc,
    get_total_and_average_confidence,
    list_policy_chunks_with_embeddings,
    list_policy_docs,
    upsert_policy_doc_with_chunks,
)


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    # SQLite needs FK enforcement turned on per-connection or the
    # ON DELETE CASCADE on PolicyChunk.doc_id is silently ignored,
    # which would make the "delete cascades chunks" test lie.
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _seed(db, category, confidence):
    db.add(EnrichmentRecord(
        narration="x", merchant="m", category=category,
        transaction_type="UPI", confidence=confidence,
    ))
    db.commit()


def test_total_and_average_confidence_on_an_empty_table_is_zero_and_none():
    # AVG() over zero rows is SQL NULL, not 0 — a "0.0 average" would
    # misleadingly claim there's data behind it when there isn't.
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    total, average = get_total_and_average_confidence(db)

    assert total == 0
    assert average is None
    db.close()


def test_total_and_average_confidence_with_data(db_session):
    _seed(db_session, "food_delivery", 0.8)
    _seed(db_session, "shopping", 0.6)

    total, average = get_total_and_average_confidence(db_session)

    assert total == 2
    assert average == pytest.approx(0.7)


def test_category_counts_groups_and_orders_by_count_descending(db_session):
    _seed(db_session, "food_delivery", 0.9)
    _seed(db_session, "food_delivery", 0.9)
    _seed(db_session, "shopping", 0.9)

    counts = get_category_counts(db_session)

    assert counts == [("food_delivery", 2), ("shopping", 1)]


def test_category_counts_on_an_empty_table_is_an_empty_list(db_session):
    assert get_category_counts(db_session) == []


# ---------------------------------------------------------------------------
# P2 — policy_docs + policy_chunks repository
# ---------------------------------------------------------------------------


def _sample_chunks(prefix: str = "c") -> list[tuple[int, str, list[float]]]:
    return [
        (0, f"{prefix}-first",  [0.1, 0.2, 0.3]),
        (1, f"{prefix}-second", [0.4, 0.5, 0.6]),
    ]


def test_upsert_inserts_a_new_doc_and_its_chunks(db_session):
    doc = upsert_policy_doc_with_chunks(
        db_session,
        doc_id="merchant_map_v3",
        title="Merchant map v3",
        checksum="sha1",
        source_uri="s3://bucket/merchant_map_v3.md",
        chunks=_sample_chunks(),
    )

    assert doc.doc_id == "merchant_map_v3"
    assert doc.source_uri == "s3://bucket/merchant_map_v3.md"
    stored = db_session.query(PolicyChunk).filter(PolicyChunk.doc_id == "merchant_map_v3").all()
    assert len(stored) == 2
    assert {c.chunk_index for c in stored} == {0, 1}
    # Embeddings persisted as JSON text — same shape as EnrichmentRecord.embedding,
    # so rag.py's single cosine loop can read both tables.
    assert json.loads(stored[0].embedding) == [0.1, 0.2, 0.3]


def test_upsert_of_same_doc_id_replaces_chunk_set_atomically(db_session):
    upsert_policy_doc_with_chunks(
        db_session, doc_id="d1", title="t1", checksum="a",
        source_uri=None, chunks=_sample_chunks("v1"),
    )
    upsert_policy_doc_with_chunks(
        db_session, doc_id="d1", title="t1-new", checksum="b",
        source_uri=None,
        chunks=[(0, "only-one", [0.9, 0.9, 0.9])],
    )

    doc = get_policy_doc(db_session, "d1")
    assert doc is not None
    assert doc.title == "t1-new"
    assert doc.checksum == "b"
    stored = db_session.query(PolicyChunk).filter(PolicyChunk.doc_id == "d1").all()
    # Old chunks GONE, new single chunk present — no half-swapped
    # state visible to any concurrent read.
    assert len(stored) == 1
    assert stored[0].content == "only-one"


def test_upsert_rejects_duplicate_chunk_index_within_same_call(db_session):
    # Would be a chunker bug — the DB catches it via the unique
    # constraint rather than letting the row set become inconsistent.
    with pytest.raises(IntegrityError):
        upsert_policy_doc_with_chunks(
            db_session, doc_id="d1", title="t", checksum="c",
            source_uri=None,
            chunks=[(0, "a", [0.1]), (0, "b", [0.2])],  # index 0 twice
        )


def test_delete_policy_doc_cascades_to_chunks(db_session):
    upsert_policy_doc_with_chunks(
        db_session, doc_id="d1", title="t", checksum="c",
        source_uri=None, chunks=_sample_chunks(),
    )
    assert db_session.query(PolicyChunk).count() == 2

    removed = delete_policy_doc(db_session, "d1")

    assert removed is True
    # FK ON DELETE CASCADE handles it in the DB — chunks vanish
    # without SQLAlchemy having to pre-load them, courtesy of
    # passive_deletes=True on the relationship.
    assert db_session.query(PolicyChunk).count() == 0
    assert get_policy_doc(db_session, "d1") is None


def test_delete_policy_doc_missing_returns_false_idempotently(db_session):
    assert delete_policy_doc(db_session, "does-not-exist") is False


def test_list_policy_docs_returns_docs_with_chunk_counts_newest_first(db_session):
    upsert_policy_doc_with_chunks(
        db_session, doc_id="old", title="old-t", checksum="a",
        source_uri=None, chunks=_sample_chunks(),
    )
    upsert_policy_doc_with_chunks(
        db_session, doc_id="new", title="new-t", checksum="b",
        source_uri=None,
        chunks=[(0, "one", [0.1])],
    )

    rows = list_policy_docs(db_session)

    # Ordered by ingested_at DESC — "new" first, "old" second.
    assert [r[0].doc_id for r in rows] == ["new", "old"]
    assert [r[1] for r in rows] == [1, 2]


def test_list_policy_chunks_with_embeddings_skips_nulls(db_session):
    upsert_policy_doc_with_chunks(
        db_session, doc_id="d1", title="t", checksum="c",
        source_uri=None, chunks=_sample_chunks(),
    )
    # Simulate a chunk that failed to embed (future backfill path).
    db_session.add(PolicyChunk(doc_id="d1", chunk_index=99, content="not-embedded", embedding=None))
    db_session.commit()

    with_emb = list_policy_chunks_with_embeddings(db_session)

    assert {c.chunk_index for c in with_emb} == {0, 1}  # 99 excluded


def test_list_policy_docs_on_empty_table_is_empty_list(db_session):
    assert list_policy_docs(db_session) == []
