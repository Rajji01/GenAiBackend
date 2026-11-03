"""
MCP arc Day 2 tests — the JSON-RPC protocol core, no network.

handle_message is pure (dict in → dict|None out), so these feed it
JSON-RPC envelopes and assert the response shapes. The DB is real
in-memory SQLite so the read-only tools actually run; the barrage test
proves end-to-end that NO MCP path mutates state.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, event, func, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from narration_enrichment import mcp_server, tools
from narration_enrichment.db import Base, EnrichmentRecord, PolicyChunk, PolicyDoc


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _fk(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    # Seed a little real data so the tools return non-trivial results.
    for merchant, category in [("Swiggy", "food_delivery"), ("Zomato", "food_delivery"),
                               ("Amazon", "shopping")]:
        session.add(EnrichmentRecord(
            narration=f"UPI/.../{merchant}/Payment", merchant=merchant,
            category=category, transaction_type="UPI", confidence=0.9,
        ))
    session.add(PolicyDoc(doc_id="merch_map", title="Merchant map", checksum="c", source_uri=None))
    session.add(PolicyChunk(doc_id="merch_map", chunk_index=0, content="SWIGGY -> food_delivery",
                            embedding=json.dumps([0.1] * 8)))
    session.commit()
    yield session
    session.close()


def _req(method, params=None, req_id=1):
    msg = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


# ---------------------------------------------------------------------------
# Handshake
# ---------------------------------------------------------------------------


def test_initialize_returns_protocol_server_and_capabilities(db):
    resp = mcp_server.handle_message(db, _req("initialize"))

    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    result = resp["result"]
    assert result["protocolVersion"] == mcp_server.PROTOCOL_VERSION
    assert result["serverInfo"]["name"] == "narration-enrichment"
    # Honest capability negotiation — we advertise tools (Day 2).
    assert "tools" in result["capabilities"]


# ---------------------------------------------------------------------------
# tools/list — rendered from the registry (drift-proof)
# ---------------------------------------------------------------------------


def test_tools_list_matches_the_registry_exactly(db):
    resp = mcp_server.handle_message(db, _req("tools/list"))

    listed = {t["name"] for t in resp["result"]["tools"]}
    # The MCP menu IS the registry's whitelist — they cannot drift,
    # because both read TOOL_REGISTRY. A tool added to the registry
    # appears here automatically; one removed disappears here.
    assert listed == set(tools.TOOL_REGISTRY.keys())


def test_tools_list_each_tool_has_name_description_and_json_schema(db):
    resp = mcp_server.handle_message(db, _req("tools/list"))

    for t in resp["result"]["tools"]:
        assert isinstance(t["name"], str) and t["name"]
        assert isinstance(t["description"], str) and t["description"]
        # inputSchema is the Pydantic args model's JSON Schema — the
        # typed-args gate, exposed to the client for client-side validation.
        assert t["inputSchema"]["type"] == "object"
        assert "properties" in t["inputSchema"]


# ---------------------------------------------------------------------------
# tools/call — happy path
# ---------------------------------------------------------------------------


def test_tools_call_count_transactions_returns_real_data(db):
    resp = mcp_server.handle_message(
        db, _req("tools/call", {"name": "count_transactions", "arguments": {}})
    )

    result = resp["result"]
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    assert payload["count"] == 3          # the 3 seeded records


def test_tools_call_find_transactions_filters(db):
    resp = mcp_server.handle_message(
        db, _req("tools/call", {"name": "find_transactions",
                                "arguments": {"category": "food_delivery"}})
    )
    payload = json.loads(resp["result"]["content"][0]["text"])
    merchants = {t["merchant"] for t in payload["transactions"]}
    assert merchants == {"Swiggy", "Zomato"}
    assert resp["result"]["isError"] is False


def test_tools_call_list_policy_docs(db):
    resp = mcp_server.handle_message(
        db, _req("tools/call", {"name": "list_policy_docs", "arguments": {}})
    )
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["docs"][0]["doc_id"] == "merch_map"


# ---------------------------------------------------------------------------
# tools/call — tool errors are isError:true CONTENT, not protocol errors
# ---------------------------------------------------------------------------


def test_unknown_tool_is_tool_error_not_protocol_error_and_names_the_menu(db):
    resp = mcp_server.handle_message(
        db, _req("tools/call", {"name": "delete_everything", "arguments": {}})
    )

    # NOT a JSON-RPC error — the transport was used correctly, the tool
    # just doesn't exist. The model recovers from an isError content.
    assert "error" not in resp
    assert resp["result"]["isError"] is True
    text = resp["result"]["content"][0]["text"]
    # The real menu is named — the whitelist's names aren't secret, and
    # a model told what exists recovers in one step (P5 rule).
    assert "find_transactions" in text


def test_bad_arguments_are_a_tool_error_with_validation_message(db):
    # find_transactions caps limit at 20; 9999 fails the Pydantic gate.
    resp = mcp_server.handle_message(
        db, _req("tools/call", {"name": "find_transactions",
                                "arguments": {"limit": 9999}})
    )
    assert "error" not in resp                    # tool-level, not protocol
    assert resp["result"]["isError"] is True
    assert "invalid arguments" in resp["result"]["content"][0]["text"].lower()


# ---------------------------------------------------------------------------
# Protocol errors — JSON-RPC -326xx
# ---------------------------------------------------------------------------


def test_tools_call_without_a_name_is_a_protocol_error(db):
    resp = mcp_server.handle_message(db, _req("tools/call", {"arguments": {}}))
    assert resp["error"]["code"] == mcp_server.INVALID_PARAMS


def test_tools_call_with_non_object_arguments_is_a_protocol_error(db):
    resp = mcp_server.handle_message(
        db, _req("tools/call", {"name": "count_transactions", "arguments": "not-an-object"})
    )
    assert resp["error"]["code"] == mcp_server.INVALID_PARAMS


def test_unknown_method_is_method_not_found(db):
    resp = mcp_server.handle_message(db, _req("tools/frobnicate"))
    assert resp["error"]["code"] == mcp_server.METHOD_NOT_FOUND


def test_bad_jsonrpc_version_is_invalid_request(db):
    resp = mcp_server.handle_message(db, {"jsonrpc": "1.0", "id": 1, "method": "initialize"})
    assert resp["error"]["code"] == mcp_server.INVALID_REQUEST


def test_non_dict_request_is_invalid_request_with_null_id(db):
    resp = mcp_server.handle_message(db, "this is not a json-rpc object")
    assert resp["error"]["code"] == mcp_server.INVALID_REQUEST
    assert resp["id"] is None


# ---------------------------------------------------------------------------
# Notifications — no reply
# ---------------------------------------------------------------------------


def test_initialized_notification_gets_no_reply(db):
    # A notification is a request with NO id. notifications/initialized
    # is the client saying the handshake is done — nothing to answer.
    resp = mcp_server.handle_message(db, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert resp is None


def test_unknown_notification_gets_no_reply(db):
    resp = mcp_server.handle_message(db, {"jsonrpc": "2.0", "method": "something/unknown"})
    assert resp is None


# ---------------------------------------------------------------------------
# resources (Day 3) — the policy corpus, read-only
# ---------------------------------------------------------------------------


def test_resources_list_exposes_policy_docs(db):
    resp = mcp_server.handle_message(db, _req("resources/list"))
    resources = resp["result"]["resources"]
    assert resources[0]["uri"] == "policy://merch_map"
    assert resources[0]["mimeType"] == "text/plain"


def test_resources_read_returns_the_doc_text(db):
    resp = mcp_server.handle_message(
        db, _req("resources/read", {"uri": "policy://merch_map"})
    )
    contents = resp["result"]["contents"]
    assert "SWIGGY -> food_delivery" in contents[0]["text"]


def test_resources_read_unknown_uri_is_invalid_params(db):
    resp = mcp_server.handle_message(
        db, _req("resources/read", {"uri": "policy://does_not_exist"})
    )
    assert resp["error"]["code"] == mcp_server.INVALID_PARAMS


def test_resources_read_bad_scheme_is_invalid_params(db):
    resp = mcp_server.handle_message(
        db, _req("resources/read", {"uri": "http://evil.example/x"})
    )
    assert resp["error"]["code"] == mcp_server.INVALID_PARAMS


def test_initialize_now_advertises_resources(db):
    resp = mcp_server.handle_message(db, _req("initialize"))
    assert "resources" in resp["result"]["capabilities"]


# ---------------------------------------------------------------------------
# The structural guarantee — NO MCP path mutates state
# ---------------------------------------------------------------------------


def test_mcp_is_read_only_end_to_end(db):
    """Fire a barrage of every MCP call — including hostile tool names —
    and assert every table's row count is unchanged. There is no MCP
    method that writes; an external client's blast radius is read-only,
    structurally (MCP_DESIGN §2)."""
    def snapshot():
        names = inspect(db.get_bind()).get_table_names()
        return {n: db.execute(
            func.count().select().select_from(Base.metadata.tables[n])
        ).scalar() for n in names if n in Base.metadata.tables}

    before = snapshot()

    barrage = [
        _req("initialize"),
        _req("tools/list"),
        _req("tools/call", {"name": "count_transactions", "arguments": {}}),
        _req("tools/call", {"name": "category_breakdown", "arguments": {}}),
        _req("tools/call", {"name": "find_transactions", "arguments": {"merchant": "Swiggy"}}),
        _req("tools/call", {"name": "list_policy_docs", "arguments": {}}),
        _req("resources/list"),
        _req("resources/read", {"uri": "policy://merch_map"}),
        # hostile / nonsense — must also change nothing
        _req("tools/call", {"name": "delete_everything", "arguments": {}}),
        _req("tools/call", {"name": "DROP TABLE enrichment_records", "arguments": {}}),
        _req("resources/read", {"uri": "policy://'; DROP TABLE policy_docs; --"}),
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
    ]
    for msg in barrage:
        mcp_server.handle_message(db, msg)

    assert snapshot() == before
