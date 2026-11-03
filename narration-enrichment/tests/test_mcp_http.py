"""
MCP arc Day 4 — the HTTP transport (POST /mcp). Compact: proves the
HTTP-transport POLICY (auth on work methods, discovery open,
notification → 204). The protocol core is covered in test_mcp_server.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from narration_enrichment import auth
from narration_enrichment.db import Base, EnrichmentRecord, get_db, insert_api_key
from narration_enrichment.main import app


_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)


@event.listens_for(_engine, "connect")
def _fk(c, _):
    cur = c.cursor(); cur.execute("PRAGMA foreign_keys=ON"); cur.close()


_Session = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
Base.metadata.create_all(_engine)


def _override():
    db = _Session()
    try:
        yield db
    finally:
        db.close()


client = TestClient(app)


@pytest.fixture(autouse=True)
def _wire():
    prev = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _override
    with _engine.begin() as conn:
        conn.execute(Base.metadata.tables["api_keys"].delete())
        conn.execute(Base.metadata.tables["enrichment_records"].delete())
    db = _Session()
    db.add(EnrichmentRecord(narration="x", merchant="Swiggy", category="food_delivery",
                            transaction_type="UPI", confidence=0.9))
    db.commit(); db.close()
    try:
        yield
    finally:
        if prev is not None:
            app.dependency_overrides[get_db] = prev
        else:
            app.dependency_overrides.pop(get_db, None)


def _key() -> str:
    raw = auth.generate_raw_key()
    db = _Session(); insert_api_key(db, key_hash=auth.hash_key(raw), label="t"); db.close()
    return raw


def test_discovery_is_open_no_key_needed():
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 200
    assert {t["name"] for t in r.json()["result"]["tools"]}  # non-empty


def test_tools_call_without_key_is_refused():
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                  "params": {"name": "count_transactions", "arguments": {}}})
    # Work method without identity → JSON-RPC error carrying the auth signal.
    assert "error" in r.json()
    assert "authentication required" in r.json()["error"]["message"]


def test_tools_call_with_key_works():
    raw = _key()
    r = client.post("/mcp", headers={"X-API-Key": raw},
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": "count_transactions", "arguments": {}}})
    assert r.status_code == 200
    assert r.json()["result"]["isError"] is False


def test_tools_call_with_bad_key_is_401():
    r = client.post("/mcp", headers={"X-API-Key": "nope"},
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": "count_transactions", "arguments": {}}})
    assert r.status_code == 401   # auth.verify_and_touch raises


def test_notification_returns_204():
    r = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert r.status_code == 204
