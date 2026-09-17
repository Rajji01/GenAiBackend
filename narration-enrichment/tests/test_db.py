"""
Unit tests for db.py's aggregation functions (Week 4's /stats), against
a real in-memory SQLite — the GROUP BY / AVG being tested is genuine SQL
behavior, not something worth mocking out.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from narration_enrichment.db import (
    Base,
    EnrichmentRecord,
    get_category_counts,
    get_total_and_average_confidence,
)


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
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
