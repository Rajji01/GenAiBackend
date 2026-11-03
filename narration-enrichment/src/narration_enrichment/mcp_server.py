"""
MCP arc Day 2 — the Model Context Protocol server core.

One pure function is the whole server logic:

    handle_message(db, request: dict, *, api_key_hash=None) -> dict | None

- Parses a JSON-RPC 2.0 envelope, dispatches on `method`, returns a
  JSON-RPC response dict — or `None` for notifications (requests with no
  `id`), which per spec get no reply. The transport layer (stdio / HTTP,
  Rajat's `pip install mcp` leg) only has to read a message, call this,
  and write the dict back if non-None.
- Every error crosses the boundary as a JSON-RPC error OBJECT, never a
  raised exception: a malformed client message is the client's bug,
  answered with the right `-326xx` code, server stays up
  (degrade-not-fail, protocol edition).

The load-bearing distinction (MCP_DESIGN §2): a bad TOOL (unknown name,
bad args, fn raised) is a tool-level `isError:true` CONTENT result — the
client's model sees it and recovers. A bad PROTOCOL message (unknown
method, missing name) is a JSON-RPC `-326xx` ERROR — the transport
itself was misused. The two are never confused.

Everything reachable over MCP is the P5 tool registry: read-only,
whitelisted, typed-args-gated. There is no MCP method that writes — an
external client's blast radius is exactly a prompt-injected internal
agent's, no more (MCP_DESIGN §0).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from narration_enrichment import tools
from narration_enrichment.db import get_policy_doc, list_policy_docs

# MCP resource URI scheme for the policy corpus: policy://<doc_id>
RESOURCE_SCHEME = "policy://"

logger = logging.getLogger(__name__)

# The MCP spec revision this core implements (date-based, per the spec).
PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "narration-enrichment"
SERVER_VERSION = "0.1.0"

# JSON-RPC 2.0 error codes (the standard reserved range).
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def _ok(req_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _tools_list() -> list[dict]:
    """Rendered FROM the registry — the MCP tool menu and the executor's
    whitelist read the same source, so they cannot drift (the
    `catalog_block()` rule). inputSchema is the args model's JSON Schema,
    which is exactly what MCP clients expect to validate against."""
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "inputSchema": tool.args_model.model_json_schema(),
        }
        for tool in tools.TOOL_REGISTRY.values()
    ]


def _tools_call(db: Session, req_id: Any, params: dict) -> dict:
    name = params.get("name")
    arguments = params.get("arguments")
    if not isinstance(name, str):
        # PROTOCOL error: the client didn't name a tool at all. This is a
        # misuse of tools/call itself, not a tool that happens to fail.
        return _err(req_id, INVALID_PARAMS, "tools/call requires a string 'name'")
    if arguments is not None and not isinstance(arguments, dict):
        return _err(req_id, INVALID_PARAMS, "'arguments' must be an object if present")

    # TOOL level: unknown name / bad args / fn raised all come back as an
    # ok=False ToolOutcome (P5's only door). They are isError:true CONTENT
    # — the model recovers — NOT a protocol error. This is the arc's
    # central distinction.
    outcome = tools.execute_tool(db, name, arguments)
    return _ok(req_id, {
        "content": [{"type": "text", "text": json.dumps(outcome.result)}],
        "isError": not outcome.ok,
    })


def _resources_list(db: Session) -> list[dict]:
    """Every ingested policy doc as a readable MCP resource. Read-only
    by construction — there is no resources/write in the spec we serve,
    and even if there were, we expose no handler for it (same structural
    guarantee as the tools side)."""
    return [
        {
            "uri": f"{RESOURCE_SCHEME}{doc.doc_id}",
            "name": doc.title,
            "description": f"Policy rulebook '{doc.title}' ({count} chunks)",
            "mimeType": "text/plain",
        }
        for doc, count in list_policy_docs(db)
    ]


def _resources_read(db: Session, req_id: Any, params: dict) -> dict:
    uri = params.get("uri")
    if not isinstance(uri, str) or not uri.startswith(RESOURCE_SCHEME):
        return _err(req_id, INVALID_PARAMS,
                    f"resources/read requires a '{RESOURCE_SCHEME}<doc_id>' uri")
    doc_id = uri[len(RESOURCE_SCHEME):]
    doc = get_policy_doc(db, doc_id)
    if doc is None:
        # Resource not found = bad params (the client named a uri that
        # doesn't resolve), a protocol-level error, not a tool error.
        return _err(req_id, INVALID_PARAMS, f"resource not found: {uri}")
    # Reassemble the doc from its chunks, in order — the raw text the
    # corpus was built from, read-only.
    text = "\n".join(chunk.content for chunk in doc.chunks)
    return _ok(req_id, {
        "contents": [{"uri": uri, "mimeType": "text/plain", "text": text}],
    })


def handle_message(
    db: Session,
    request: Any,
    *,
    api_key_hash: str | None = None,
) -> dict | None:
    """Dispatch one JSON-RPC 2.0 message. Returns a response dict, or
    None for a notification (no `id`). `api_key_hash` is threaded for
    Day-4 auth enforcement; Day 2 accepts it but does not yet gate on
    it (tools over MCP are all cheap read-only queries).
    """
    if not isinstance(request, dict):
        return _err(None, INVALID_REQUEST, "Invalid Request: not a JSON-RPC object")

    req_id = request.get("id")
    # A JSON-RPC NOTIFICATION is a request with NO `id` member — it gets
    # no reply, ever (the wire-format detail the tests pin).
    is_notification = "id" not in request

    if request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
        if is_notification:
            return None
        return _err(req_id, INVALID_REQUEST, "Invalid Request: bad jsonrpc/method")

    method = request["method"]
    params = request.get("params") or {}
    if not isinstance(params, dict):
        if is_notification:
            return None
        return _err(req_id, INVALID_PARAMS, "'params' must be an object")

    # --- notifications (no reply) ------------------------------------
    if method.startswith("notifications/"):
        # e.g. notifications/initialized — the client telling us the
        # handshake is done. Nothing to answer.
        return None

    # --- handshake ---------------------------------------------------
    if method == "initialize":
        # Capability negotiation, honest: advertise only what we serve.
        # Day 2 = tools. resources joins on Day 3.
        return _ok(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            # Day 3: we now serve tools AND resources — advertise both.
            "capabilities": {"tools": {}, "resources": {}},
        })

    # --- tools -------------------------------------------------------
    if method == "tools/list":
        return _ok(req_id, {"tools": _tools_list()})

    if method == "tools/call":
        try:
            return _tools_call(db, req_id, params)
        except Exception as exc:  # noqa: BLE001 — never raise across the boundary
            logger.error("mcp_tools_call_unexpected error=%s", exc, exc_info=exc)
            return _err(req_id, INTERNAL_ERROR, "Internal error")

    # --- resources (Day 3) -------------------------------------------
    if method == "resources/list":
        return _ok(req_id, {"resources": _resources_list(db)})

    if method == "resources/read":
        try:
            return _resources_read(db, req_id, params)
        except Exception as exc:  # noqa: BLE001
            logger.error("mcp_resources_read_unexpected error=%s", exc, exc_info=exc)
            return _err(req_id, INTERNAL_ERROR, "Internal error")

    # --- unknown method ----------------------------------------------
    if is_notification:
        return None
    return _err(req_id, METHOD_NOT_FOUND, f"Method not found: {method}")
