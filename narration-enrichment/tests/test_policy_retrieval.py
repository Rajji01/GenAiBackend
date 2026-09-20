"""
P2 Day 5 tests — policy-chunk retrieval + prompt-block build + the
earned-citations rule at the route boundary.

Unit tests exercise rag.retrieve_policy_chunks + build_policy_context_block
directly against real in-memory SQLite (the cosine + JSON-decode is
what's being tested; mocking those away would test the mock).

Integration test drives POST /enrich end-to-end with the LLM mocked at
main's enrich_narration boundary, and asserts:
1. When a policy chunk matches, policy_context is passed to
   enrich_narration.
2. The response's policy_citations comes from GROUND TRUTH (retrieval
   result), not from whatever the LLM's function-calling handed back —
   this is the "citations are earned, not decorative" contract in
   P2_DESIGN.md sec 6.
"""

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from narration_enrichment import rag
from narration_enrichment.db import Base, PolicyChunk, PolicyDoc, get_db
from narration_enrichment.main import app, rate_limiter
from narration_enrichment.models import Citation, TransactionEnrichment


FAKE_EMBEDDING = [0.1] * 8   # short vector — 8 dims is enough for these tests
DIFFERENT_EMBEDDING = [0.9] + [0.0] * 7   # cosine-far from FAKE_EMBEDDING


# ---------------------------------------------------------------------------
# Unit — rag.retrieve_policy_chunks + build_policy_context_block
# ---------------------------------------------------------------------------


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


def _seed_policy_chunk(db, doc_id, chunk_index, content, embedding):
    # Doc row is required by the FK. checksum + title kept minimal.
    if not db.query(PolicyDoc).filter(PolicyDoc.doc_id == doc_id).first():
        db.add(PolicyDoc(doc_id=doc_id, title="t", checksum="c", source_uri=None))
    db.add(PolicyChunk(
        doc_id=doc_id, chunk_index=chunk_index,
        content=content, embedding=json.dumps(embedding),
    ))
    db.commit()


def test_retrieve_policy_chunks_returns_scored_pairs_ordered_desc(db_session):
    # Two chunks: one identical to the query vector (cosine=1.0), one
    # far from it (cosine well below the floor). Only the close one
    # should come back.
    _seed_policy_chunk(db_session, "d1", 0, "SWIGGY -> food_delivery", FAKE_EMBEDDING)
    _seed_policy_chunk(db_session, "d1", 1, "unrelated content", DIFFERENT_EMBEDDING)

    result = rag.retrieve_policy_chunks(db_session, FAKE_EMBEDDING)

    assert len(result) == 1
    score, chunk = result[0]
    assert score == pytest.approx(1.0, abs=1e-6)
    assert chunk.chunk_index == 0


def test_retrieve_policy_chunks_respects_top_k_cap(db_session):
    for i in range(5):
        _seed_policy_chunk(db_session, "d1", i, f"chunk-{i}", FAKE_EMBEDDING)

    result = rag.retrieve_policy_chunks(db_session, FAKE_EMBEDDING, top_k=2)

    # All 5 clear the floor (cosine=1.0), but the top_k cap keeps only 2.
    assert len(result) == 2


def test_retrieve_policy_chunks_returns_empty_when_below_similarity_floor(db_session):
    _seed_policy_chunk(db_session, "d1", 0, "unrelated", DIFFERENT_EMBEDDING)

    result = rag.retrieve_policy_chunks(db_session, FAKE_EMBEDDING, min_similarity=0.65)

    # DIFFERENT_EMBEDDING's cosine with FAKE_EMBEDDING is well under 0.65,
    # so no results — the prompt gets no policy block, model falls back
    # to base behavior.
    assert result == []


def test_retrieve_policy_chunks_skips_chunks_with_null_embedding(db_session):
    _seed_policy_chunk(db_session, "d1", 0, "embedded", FAKE_EMBEDDING)
    # A chunk that failed to embed (backfill flow). Shouldn't be
    # searchable — list_policy_chunks_with_embeddings filters it out.
    if not db_session.query(PolicyDoc).filter(PolicyDoc.doc_id == "d1").first():
        db_session.add(PolicyDoc(doc_id="d1", title="t", checksum="c", source_uri=None))
    db_session.add(PolicyChunk(
        doc_id="d1", chunk_index=99, content="not-embedded", embedding=None,
    ))
    db_session.commit()

    result = rag.retrieve_policy_chunks(db_session, FAKE_EMBEDDING)

    assert len(result) == 1
    assert result[0][1].chunk_index == 0


def test_build_policy_context_block_returns_none_for_empty():
    assert rag.build_policy_context_block([]) is None


def test_build_policy_context_block_labels_chunks_as_rules_not_evidence():
    # This is the prompt-engineering intent: the label word "policy" +
    # the wording "treat these as rules" is what differentiates the
    # signal from Week 3's past-narration block ("guidance for
    # consistency"). If a future refactor drops that distinction, this
    # test catches it.
    class _StubChunk:
        doc_id = "merchant_map_v3"
        chunk_index = 4
        content = "SWIGGY -> food_delivery"

    block = rag.build_policy_context_block([(0.83, _StubChunk())])

    assert block is not None
    assert "policy" in block.lower()
    assert "rules" in block.lower()
    assert "merchant_map_v3" in block
    assert "SWIGGY -> food_delivery" in block


# ---------------------------------------------------------------------------
# Integration — /enrich populates policy_citations from GROUND TRUTH
# ---------------------------------------------------------------------------


_test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


@event.listens_for(_test_engine, "connect")
def _fk_on_test_engine(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


_TestSessionLocal = sessionmaker(bind=_test_engine, autoflush=False, autocommit=False)
Base.metadata.create_all(_test_engine)

client = TestClient(app)


def _override_get_db():
    db = _TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _install_override():
    # Same pattern as test_policy_api.py: don't stomp on test_api.py's
    # module-level override; install ours only for the duration of
    # each test in this file, then put back whatever was there.
    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield
    finally:
        if previous is not None:
            app.dependency_overrides[get_db] = previous
        else:
            app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def _clean_tables_and_reset_limiter():
    with _test_engine.begin() as conn:
        conn.execute(Base.metadata.tables["enrichment_records"].delete())
        conn.execute(Base.metadata.tables["policy_chunks"].delete())
        conn.execute(Base.metadata.tables["policy_docs"].delete())
    # Rate limiter shares module-level state with tests/test_api.py;
    # clear it so the 429 test in test_api.py doesn't leak into ours.
    # (Internal window deques; per rate_limiter._Window/_RateLimiter.)
    rate_limiter._minute.calls.clear()
    rate_limiter._day.calls.clear()
    yield


@pytest.fixture(autouse=True)
def _mock_embed():
    # Same rag.embed_text seam every other integration test uses.
    with patch("narration_enrichment.rag.embed_text", return_value=FAKE_EMBEDDING):
        yield


def _seed_matching_policy_chunk(doc_id="merchant_map", chunk_index=0,
                                content="SWIGGY -> food_delivery"):
    db = _TestSessionLocal()
    if not db.query(PolicyDoc).filter(PolicyDoc.doc_id == doc_id).first():
        db.add(PolicyDoc(doc_id=doc_id, title="t", checksum="c", source_uri=None))
    db.add(PolicyChunk(
        doc_id=doc_id, chunk_index=chunk_index,
        content=content, embedding=json.dumps(FAKE_EMBEDDING),
    ))
    db.commit()
    db.close()


def test_enrich_passes_policy_context_when_a_chunk_matches():
    _seed_matching_policy_chunk()
    fake_result = TransactionEnrichment(
        merchant="Swiggy", category="food_delivery", transaction_type="UPI", confidence=0.9
    )
    with patch(
        "narration_enrichment.main.enrich_narration", return_value=fake_result
    ) as mock_enrich:
        r = client.post("/enrich", json={"narration": "UPI/P2M/.../SWIGGY/Payment"})

    assert r.status_code == 200
    _, kwargs = mock_enrich.call_args
    # policy_context flows into enrich_narration as a labeled block
    # containing the seeded chunk's content.
    assert kwargs["policy_context"] is not None
    assert "SWIGGY -> food_delivery" in kwargs["policy_context"]
    assert "policy" in kwargs["policy_context"].lower()


def test_enrich_response_carries_ground_truth_citations_from_retrieval():
    _seed_matching_policy_chunk(chunk_index=7, content="OLA -> transportation")
    fake_result = TransactionEnrichment(
        merchant="Ola", category="transfer", transaction_type="UPI", confidence=0.8
    )
    with patch("narration_enrichment.main.enrich_narration", return_value=fake_result):
        r = client.post("/enrich", json={"narration": "UPI/P2M/.../OLA/Payment"})

    assert r.status_code == 200
    body = r.json()
    citations = body["policy_citations"]
    # ONE citation, matching the ONE seeded chunk, with the score the
    # cosine loop actually computed (1.0 in this mocked-embedding
    # setup) — not something the LLM invented.
    assert len(citations) == 1
    assert citations[0]["doc_id"] == "merchant_map"
    assert citations[0]["chunk_index"] == 7
    assert citations[0]["snippet"] == "OLA -> transportation"
    assert citations[0]["similarity_score"] == pytest.approx(1.0, abs=1e-6)


def test_llm_provided_citations_are_overwritten_not_appended():
    """The earned-citations contract: even if enrich_narration returns
    a TransactionEnrichment with policy_citations of its own (as
    Instructor's function-calling could), the route overwrites it from
    the retrieval result. Model doesn't get to choose what to cite."""
    _seed_matching_policy_chunk(chunk_index=0, content="REAL policy chunk")
    hallucinated = TransactionEnrichment(
        merchant="Swiggy", category="food_delivery", transaction_type="UPI", confidence=0.9,
        policy_citations=[
            Citation(
                doc_id="hallucinated_doc",
                chunk_index=999,
                snippet="a chunk that was never retrieved",
                similarity_score=0.99,
            )
        ],
    )
    with patch("narration_enrichment.main.enrich_narration", return_value=hallucinated):
        r = client.post("/enrich", json={"narration": "UPI/P2M/.../SWIGGY/Payment"})

    assert r.status_code == 200
    citations = r.json()["policy_citations"]
    # ONE citation — the real retrieval result. The LLM's invented
    # citation is gone. If this test starts failing, the earned-
    # citations rule has been broken; that's a hallucination class
    # slipping into production.
    assert len(citations) == 1
    assert citations[0]["doc_id"] == "merchant_map"
    assert citations[0]["chunk_index"] == 0
    assert citations[0]["snippet"] == "REAL policy chunk"


def test_enrich_returns_empty_citations_when_no_policy_chunks_match():
    fake_result = TransactionEnrichment(
        merchant="Something", category="other", transaction_type="UPI", confidence=0.5
    )
    with patch("narration_enrichment.main.enrich_narration", return_value=fake_result):
        r = client.post("/enrich", json={"narration": "UPI/P2M/.../UNKNOWN/Payment"})

    assert r.status_code == 200
    # No seeded chunks → no citations. Not None, not missing — an
    # explicit empty list, matching TransactionEnrichment's default.
    assert r.json()["policy_citations"] == []
