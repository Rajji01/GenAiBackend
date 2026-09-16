"""
Unit tests for rag.py's retrieval logic — pure math and DB queries, no
embedding API calls. embed_text (the actual network call) is exercised
through the mocked path in test_api.py instead; this file is about
whether the retrieval and ranking logic is correct once you already have
vectors.
"""

import json
import math

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from narration_enrichment.db import Base, EnrichmentRecord
from narration_enrichment.rag import build_context_block, cosine_similarity, find_similar_examples


def test_cosine_similarity_of_identical_vectors_is_one():
    v = [0.3, 0.6, 0.1]
    assert cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_similarity_of_orthogonal_vectors_is_zero():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_of_opposite_vectors_is_negative_one():
    assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_cosine_similarity_handles_a_zero_vector_without_dividing_by_zero():
    # A defensive case, not a realistic embedding — but a bug here would
    # be a crash, not a wrong number, so it's worth pinning down.
    assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _seed(db, narration, merchant, category, embedding):
    record = EnrichmentRecord(
        narration=narration,
        merchant=merchant,
        category=category,
        transaction_type="UPI",
        confidence=0.9,
        embedding=json.dumps(embedding),
    )
    db.add(record)
    db.commit()
    return record


def test_find_similar_examples_returns_nothing_from_an_empty_history(db_session):
    assert find_similar_examples(db_session, query_embedding=[1.0, 0.0]) == []


def test_find_similar_examples_excludes_results_below_the_similarity_floor(db_session):
    _seed(db_session, "unrelated narration", "Unrelated Co", "other", embedding=[0.0, 1.0])
    # Orthogonal to the query -> similarity 0.0, nowhere near MIN_SIMILARITY.
    results = find_similar_examples(db_session, query_embedding=[1.0, 0.0])
    assert results == []


def test_find_similar_examples_ranks_the_closest_match_first(db_session):
    _seed(db_session, "somewhat similar", "Somewhat Co", "shopping", embedding=[0.9, math.sqrt(1 - 0.9**2)])
    _seed(db_session, "very similar", "Very Co", "shopping", embedding=[0.99, math.sqrt(1 - 0.99**2)])

    results = find_similar_examples(db_session, query_embedding=[1.0, 0.0], top_k=2, min_similarity=0.5)

    assert [r.merchant for r in results] == ["Very Co", "Somewhat Co"]


def test_find_similar_examples_respects_top_k(db_session):
    for i in range(5):
        _seed(db_session, f"narration {i}", f"Merchant {i}", "shopping", embedding=[1.0, 0.0])

    results = find_similar_examples(db_session, query_embedding=[1.0, 0.0], top_k=2, min_similarity=0.5)
    assert len(results) == 2


def test_build_context_block_is_none_for_no_examples():
    assert build_context_block([]) is None


def test_build_context_block_includes_merchant_and_category():
    record = EnrichmentRecord(
        narration="UPI/P2M/.../SWIGGY/Payment",
        merchant="Swiggy",
        category="food_delivery",
        transaction_type="UPI",
        confidence=0.9,
    )
    block = build_context_block([record])
    assert "Swiggy" in block
    assert "food_delivery" in block
    assert "UPI/P2M/.../SWIGGY/Payment" in block
