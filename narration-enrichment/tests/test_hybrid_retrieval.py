"""
P7 Day 2 — hybrid retrieval: BM25 + dense, fused by RRF.

Three layers under test, no network anywhere:
- bm25.py as pure functions (tokenizer, scoring, idf floor, RRF);
- rag.hybrid_* against a seeded SQLite (the two channels' union,
  floors on the dense side only, lexical-only on embedding=None);
- the availability upgrade end-to-end: /enrich with the embed
  endpoint DOWN still gets real lexical context into the prompt —
  the claim that used to be "degrades to empty" is now "degrades to
  BM25-only", and the prompt is the proof.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import narration_enrichment.main as main_module
from narration_enrichment import rag
from narration_enrichment.bm25 import BM25, rrf_fuse, tokenize
from narration_enrichment.db import Base, EnrichmentRecord, PolicyChunk, PolicyDoc, get_db
from narration_enrichment.main import app
from narration_enrichment.models import TransactionEnrichment
from narration_enrichment.rate_limiter import RateLimiter


# --- bm25.py: the pure layer ---------------------------------------------------


def test_tokenizer_is_the_domain_right_alnum_split():
    assert tokenize("UPI/NETFLIX/Payment-2024") == ["upi", "netflix", "payment", "2024"]


def test_exact_token_match_outranks_non_matching_docs():
    docs = [
        "UPI/NETFLIX/Payment",
        "UPI/SWIGGY/Payment",
        "NEFT salary credit",
    ]
    scores = BM25(docs).scores("netflix subscription")

    assert scores[0] > 0
    assert scores[1] == 0 or scores[0] > scores[1]
    assert scores[2] == 0.0  # zero term overlap = the lexical entry bar


def test_rare_term_outweighs_common_term():
    # 'payment' appears everywhere (low idf); 'netflix' once (high idf).
    docs = ["upi netflix payment", "upi swiggy payment", "upi uber payment"]
    scores = BM25(docs).scores("netflix payment")

    assert scores[0] > scores[1]
    # The common-term-only docs still tie with each other.
    assert scores[1] == pytest.approx(scores[2])


def test_idf_never_goes_negative_for_very_common_terms():
    # Classic BM25's idf can go negative for a term in >half the
    # corpus, making a MATCH score worse than no match. The floor
    # keeps a common-term match at worst neutral.
    docs = ["payment one", "payment two", "payment three"]
    scores = BM25(docs).scores("payment")

    assert all(s >= 0 for s in scores)


def test_rrf_appearing_in_both_channels_beats_topping_one():
    both = rrf_fuse([[1, 2], [1, 3]])
    assert both[1] > both[2]
    assert both[1] > both[3]
    # Absence from a channel is no PENALTY — just no contribution.
    assert both[2] == pytest.approx(1.0 / 62)


# --- rag.hybrid_*: the two channels against a seeded DB ---------------------------


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


EMB_A = [1.0, 0.0, 0.0, 0.0]
EMB_B = [0.0, 1.0, 0.0, 0.0]


def _seed_record(db, narration, embedding=None):
    r = EnrichmentRecord(
        narration=narration, merchant="m", category="other",
        transaction_type="upi", confidence=0.9,
        embedding=json.dumps(embedding) if embedding is not None else None,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def test_lexical_only_when_embedding_is_none(db_session):
    hit = _seed_record(db_session, "UPI/NETFLIX/Payment", embedding=EMB_A)
    _seed_record(db_session, "NEFT salary credit", embedding=EMB_B)

    results = rag.hybrid_find_similar_examples(db_session, "netflix charge", None)

    assert [r.id for r in results] == [hit.id]


def test_lexical_channel_resurrects_rows_dense_can_never_see(db_session):
    # Saved during an embed outage: embedding=None, invisible to cosine
    # FOREVER. BM25 finds it by its tokens — the P7 availability win.
    orphan = _seed_record(db_session, "UPI/NETFLIX/Payment", embedding=None)

    results = rag.hybrid_find_similar_examples(db_session, "netflix", EMB_A)

    assert orphan.id in [r.id for r in results]


def test_dense_floor_still_gates_the_dense_channel(db_session):
    # A record that is lexically unrelated AND below the cosine floor
    # must not appear at all; one above the floor enters via dense even
    # with zero token overlap.
    close = _seed_record(db_session, "zzz qqq", embedding=EMB_A)        # cosine 1.0 to query
    far = _seed_record(db_session, "yyy www", embedding=EMB_B)          # cosine 0.0

    results = rag.hybrid_find_similar_examples(db_session, "netflix", EMB_A)

    ids = [r.id for r in results]
    assert close.id in ids      # dense channel, despite no shared tokens
    assert far.id not in ids    # below floor + no overlap = absent


def test_candidate_in_both_channels_outranks_single_channel(db_session):
    both = _seed_record(db_session, "UPI/NETFLIX/Payment", embedding=EMB_A)
    dense_only = _seed_record(db_session, "zzz qqq", embedding=EMB_A)

    results = rag.hybrid_find_similar_examples(db_session, "netflix payment", EMB_A)

    assert results[0].id == both.id
    assert dense_only.id in [r.id for r in results]


def test_policy_hybrid_returns_fused_scores_for_citations(db_session):
    db_session.add(PolicyDoc(doc_id="d1", title="t", checksum="c"))
    db_session.add(PolicyChunk(doc_id="d1", chunk_index=0,
                               content="NETFLIX and streaming subscriptions are entertainment",
                               embedding=json.dumps(EMB_A)))
    db_session.commit()

    scored = rag.hybrid_retrieve_policy_chunks(db_session, "netflix charge", EMB_A)

    assert len(scored) == 1
    fused_score, chunk = scored[0]
    assert chunk.doc_id == "d1"
    # In both channels → both RRF contributions at rank 1.
    assert fused_score == pytest.approx(2.0 / 61)


# --- the availability upgrade, end to end ------------------------------------------


_test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSessionLocal = sessionmaker(bind=_test_engine, autoflush=False, autocommit=False)
Base.metadata.create_all(_test_engine)


def _override_get_db():
    db = _TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


client = TestClient(app)


def test_enrich_keeps_real_context_through_an_embed_outage(monkeypatch):
    with _test_engine.begin() as conn:
        conn.execute(Base.metadata.tables["enrichment_records"].delete())
    db = _TestSessionLocal()
    try:
        db.add(EnrichmentRecord(
            narration="UPI/NETFLIX/Payment", merchant="Netflix",
            category="entertainment", transaction_type="upi",
            confidence=0.95, embedding=None,
        ))
        db.commit()
    finally:
        db.close()

    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _override_get_db
    monkeypatch.setattr(main_module, "rate_limiter", RateLimiter(per_minute=1000, per_day=10000))
    healthy = MagicMock(return_value=TransactionEnrichment(
        merchant="Netflix", category="other", transaction_type="upi",
        confidence=0.9, human_narration="Netflix subscription",
    ))
    try:
        with patch(
            "narration_enrichment.rag.embed_text",
            side_effect=RuntimeError("embed endpoint down"),
        ), patch("narration_enrichment.service._call_llm", healthy):
            r = client.post("/enrich", json={"narration": "UPI/NETFLIX/Payment renewal"})

        assert r.status_code == 200
        # Pre-P7 this outage meant context=None. Now the lexical channel
        # delivered the past classification into the prompt — the proof
        # is the prompt itself.
        _narration, context_kw, _policy = (
            healthy.call_args.args if healthy.call_args.args else (None, None, None)
        )
        context = healthy.call_args.args[1] if healthy.call_args.args else healthy.call_args.kwargs.get("context")
        assert context is not None and "UPI/NETFLIX/Payment" in context
    finally:
        if previous is not None:
            app.dependency_overrides[get_db] = previous
        else:
            app.dependency_overrides.pop(get_db, None)
