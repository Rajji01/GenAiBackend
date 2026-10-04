"""
P5 Day 2 — unit tests for the tool registry.

Pure DB: every tool is a read-only function over a seeded SQLite —
nothing mocked, no LLM anywhere. The execute_tool gate (whitelist →
validate → run → observation) is tested with the same rigor as the
tools, because the gate IS the guardrail (P5_DESIGN.md §2).
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from narration_enrichment import tools
from narration_enrichment.db import Base, EnrichmentRecord, PolicyChunk, PolicyDoc
from narration_enrichment.tools import TOOL_REGISTRY, ToolOutcome, catalog_block, execute_tool


_test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


@event.listens_for(_test_engine, "connect")
def _fk_on(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


_TestSessionLocal = sessionmaker(bind=_test_engine, autoflush=False, autocommit=False)
Base.metadata.create_all(_test_engine)

NOW = datetime.now(timezone.utc)


@pytest.fixture()
def db():
    with _test_engine.begin() as conn:
        conn.execute(Base.metadata.tables["policy_chunks"].delete())
        conn.execute(Base.metadata.tables["policy_docs"].delete())
        conn.execute(Base.metadata.tables["enrichment_records"].delete())
    session = _TestSessionLocal()
    try:
        yield session
    finally:
        session.close()


def _seed_record(db, *, merchant="Swiggy", category="food_delivery", age_days=0.0):
    r = EnrichmentRecord(
        narration=f"UPI/{merchant}/Payment",
        merchant=merchant,
        category=category,
        transaction_type="upi",
        confidence=0.9,
        created_at=NOW - timedelta(days=age_days),
    )
    db.add(r)
    db.commit()
    return r


def _seed_policy(db, *, doc_id="d1", title="Rules", chunks=2):
    db.add(PolicyDoc(doc_id=doc_id, title=title, checksum="x" * 64))
    for i in range(chunks):
        db.add(PolicyChunk(doc_id=doc_id, chunk_index=i, content=f"c{i}", embedding="[]"))
    db.commit()


# --- count_transactions -------------------------------------------------------


def test_count_with_no_filters_counts_everything(db):
    _seed_record(db)
    _seed_record(db, merchant="Zomato")
    _seed_record(db, merchant="Uber", category="transport")

    out = execute_tool(db, "count_transactions", {})

    assert out.ok is True
    assert out.result == {"count": 3}


def test_count_filters_are_case_insensitive_exact_matches(db):
    _seed_record(db, merchant="Swiggy", category="food_delivery")
    _seed_record(db, merchant="Zomato", category="food_delivery")
    _seed_record(db, merchant="Uber", category="transport")

    assert execute_tool(db, "count_transactions", {"category": "FOOD_DELIVERY"}).result == {"count": 2}
    assert execute_tool(db, "count_transactions", {"merchant": "swiggy"}).result == {"count": 1}
    # Exact, not fuzzy — a substring must NOT match (that is retrieval's job).
    assert execute_tool(db, "count_transactions", {"merchant": "Swig"}).result == {"count": 0}


def test_count_days_window_excludes_older_records(db):
    _seed_record(db, age_days=1)
    _seed_record(db, age_days=40)

    out = execute_tool(db, "count_transactions", {"days": 30})

    assert out.result == {"count": 1}


# --- category_breakdown ---------------------------------------------------------


def test_breakdown_returns_whole_distribution_largest_first(db):
    for _ in range(3):
        _seed_record(db, category="food_delivery")
    _seed_record(db, merchant="Uber", category="transport")

    out = execute_tool(db, "category_breakdown", {})

    assert out.ok is True
    assert out.result["categories"] == [
        {"category": "food_delivery", "count": 3},
        {"category": "transport", "count": 1},
    ]


def test_breakdown_on_empty_table_is_an_empty_list_not_an_error(db):
    out = execute_tool(db, "category_breakdown", {})

    assert out.ok is True
    assert out.result == {"categories": []}


# --- find_transactions -----------------------------------------------------------


def test_find_lists_exact_matches_newest_first_with_limit(db):
    first = _seed_record(db, merchant="Swiggy")
    second = _seed_record(db, merchant="Swiggy")
    _seed_record(db, merchant="Zomato")

    out = execute_tool(db, "find_transactions", {"merchant": "swiggy", "limit": 1})

    assert out.ok is True
    txns = out.result["transactions"]
    assert [t["id"] for t in txns] == [second.id]  # newest first, limit respected

    out_all = execute_tool(db, "find_transactions", {"merchant": "swiggy"})
    assert [t["id"] for t in out_all.result["transactions"]] == [second.id, first.id]


def test_find_limit_above_bound_is_rejected_in_validation(db):
    _seed_record(db)

    out = execute_tool(db, "find_transactions", {"limit": 10_000})

    assert out.ok is False
    assert "invalid arguments" in out.result["error"]


# --- list_policy_docs --------------------------------------------------------------


def test_list_policy_docs_reports_inventory_with_chunk_counts(db):
    _seed_policy(db, doc_id="merchant_map", title="Merchant Map", chunks=3)
    _seed_policy(db, doc_id="subs_rules", title="Subscriptions", chunks=1)

    out = execute_tool(db, "list_policy_docs", {})

    assert out.ok is True
    by_id = {d["doc_id"]: d for d in out.result["docs"]}
    assert by_id["merchant_map"] == {"doc_id": "merchant_map", "title": "Merchant Map", "chunks": 3}
    assert by_id["subs_rules"]["chunks"] == 1


# --- the gate: execute_tool ----------------------------------------------------------


def test_unknown_tool_is_an_observation_naming_the_real_menu(db):
    out = execute_tool(db, "delete_everything", {})

    assert out.ok is False
    assert "unknown tool" in out.result["error"]
    assert out.result["available"] == sorted(TOOL_REGISTRY.keys())


def test_invalid_args_become_an_observation_not_an_exception(db):
    out = execute_tool(db, "count_transactions", {"days": "yesterday"})

    assert out.ok is False
    assert "invalid arguments" in out.result["error"]


def test_tool_runtime_failure_degrades_to_ok_false(db, monkeypatch):
    # Force the one failure validation can't catch: the function
    # itself blowing up (a DB hiccup). The gate must convert it to an
    # observation — the chat never dies for a tool.
    broken = tools.Tool(
        name="count_transactions",
        description="broken for this test",
        args_model=tools.CountTransactionsArgs,
        fn=lambda db_, args: (_ for _ in ()).throw(RuntimeError("db went away")),
    )
    monkeypatch.setitem(TOOL_REGISTRY, "count_transactions", broken)

    out = execute_tool(db, "count_transactions", {})

    assert out.ok is False
    assert out.result["error"] == "tool execution failed: RuntimeError"


def test_catalog_block_is_rendered_from_the_registry():
    text = catalog_block()

    # One source, two views: every registered tool appears with its
    # arg names; a tool added later shows up with zero extra wiring.
    for name in TOOL_REGISTRY:
        assert name in text
    assert "merchant" in text and "days" in text
    assert "amounts are NOT captured" in text  # the honesty note reaches the model


def test_every_registry_outcome_is_a_tooloutcome(db):
    for name in TOOL_REGISTRY:
        out = execute_tool(db, name, {})
        assert isinstance(out, ToolOutcome)
        assert out.ok is True, f"{name} failed on empty valid args: {out.result}"
