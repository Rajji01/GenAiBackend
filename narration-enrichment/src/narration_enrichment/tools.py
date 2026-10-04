"""
P5 Day 2 — the tool registry: four deterministic, read-only tools
over the database, behind a whitelist.

Why these exist at all (P5_DESIGN.md §1): similarity retrieval
answers "show me things LIKE this"; it structurally cannot answer
exact counts (top-k returns k rows by construction), exhaustive
filters (floors and k truncate), or inventory ("which rulebooks do
you have?" — there is no embedding of absence). These four tools are
the exact channel next to P3's fuzzy one.

Honesty constraint: `enrichment_records` has NO amount column, so no
tool here sums money. "How much did I spend" gets counts and
breakdowns plus the model saying amounts aren't captured — a tool
inventing spend totals would be the tool-shaped version of a
hallucinated citation.

Three load-bearing properties (P5_DESIGN.md §2):
- WHITELIST: `execute_tool` runs a tool iff its name is in
  TOOL_REGISTRY. Nothing the model writes can conjure capability
  code didn't register.
- TYPED ARGS: the raw dict the LLM produced goes through the tool's
  Pydantic model BEFORE the function runs. A bad shape becomes an
  error observation, never a SQL parameter.
- READ-ONLY: every fn is a pure query over the Session. The loop can
  never be tricked into mutating state — the structural nine tenths
  of injection defence.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func
from sqlalchemy.orm import Session

from narration_enrichment.db import EnrichmentRecord, list_policy_docs

logger = logging.getLogger(__name__)


# --- outcomes ---------------------------------------------------------------


@dataclass(frozen=True)
class ToolOutcome:
    """What one execution attempt produced. `ok=False` outcomes carry
    an `error` key in `result` — they are observations for the model
    (and audit rows), never exceptions for the caller: a failed tool
    must not kill the chat (degrade-not-fail)."""

    tool_name: str
    ok: bool
    result: dict


# --- per-tool argument models ------------------------------------------------
#
# Bounds are part of the contract the MODEL sees (Instructor exposes
# them via the schema) and part of the defence (a hostile `limit` of
# 10**9 dies in validation, not in the DB).


class CountTransactionsArgs(BaseModel):
    category: str | None = Field(default=None, description="Exact category, case-insensitive.")
    merchant: str | None = Field(default=None, description="Exact merchant name, case-insensitive.")
    days: int | None = Field(default=None, ge=1, le=3650, description="Only records from the last N days.")


class CategoryBreakdownArgs(BaseModel):
    days: int | None = Field(default=None, ge=1, le=3650, description="Only records from the last N days.")


class FindTransactionsArgs(BaseModel):
    merchant: str | None = Field(default=None, description="Exact merchant name, case-insensitive.")
    category: str | None = Field(default=None, description="Exact category, case-insensitive.")
    limit: int = Field(default=10, ge=1, le=20, description="Max rows returned, newest first.")


class ListPolicyDocsArgs(BaseModel):
    pass


# --- the four functions -------------------------------------------------------


def _since(days: int | None) -> datetime | None:
    return None if days is None else datetime.now(timezone.utc) - timedelta(days=days)


def _count_transactions(db: Session, args: CountTransactionsArgs) -> dict:
    q = db.query(func.count(EnrichmentRecord.id))
    if args.category is not None:
        q = q.filter(func.lower(EnrichmentRecord.category) == args.category.lower())
    if args.merchant is not None:
        q = q.filter(func.lower(EnrichmentRecord.merchant) == args.merchant.lower())
    cutoff = _since(args.days)
    if cutoff is not None:
        q = q.filter(EnrichmentRecord.created_at >= cutoff)
    return {"count": int(q.scalar() or 0)}


def _category_breakdown(db: Session, args: CategoryBreakdownArgs) -> dict:
    q = db.query(EnrichmentRecord.category, func.count(EnrichmentRecord.id))
    cutoff = _since(args.days)
    if cutoff is not None:
        q = q.filter(EnrichmentRecord.created_at >= cutoff)
    rows = (
        q.group_by(EnrichmentRecord.category)
        .order_by(func.count(EnrichmentRecord.id).desc())
        .all()
    )
    return {"categories": [{"category": c, "count": int(n)} for c, n in rows]}


def _find_transactions(db: Session, args: FindTransactionsArgs) -> dict:
    q = db.query(EnrichmentRecord)
    if args.merchant is not None:
        q = q.filter(func.lower(EnrichmentRecord.merchant) == args.merchant.lower())
    if args.category is not None:
        q = q.filter(func.lower(EnrichmentRecord.category) == args.category.lower())
    rows = q.order_by(EnrichmentRecord.id.desc()).limit(args.limit).all()
    return {
        "transactions": [
            {
                "id": r.id,
                "merchant": r.merchant,
                "category": r.category,
                "transaction_type": r.transaction_type,
                "narration": r.narration,
            }
            for r in rows
        ]
    }


def _list_policy_docs(db: Session, args: ListPolicyDocsArgs) -> dict:
    return {
        "docs": [
            {"doc_id": doc.doc_id, "title": doc.title, "chunks": count}
            for doc, count in list_policy_docs(db)
        ]
    }


# --- the registry -------------------------------------------------------------


@dataclass(frozen=True)
class Tool:
    name: str
    description: str  # what the MODEL reads when choosing a tool
    args_model: type[BaseModel]
    fn: Callable[[Session, BaseModel], dict]


TOOL_REGISTRY: dict[str, Tool] = {
    t.name: t
    for t in (
        Tool(
            name="count_transactions",
            description=(
                "Exact count of enrichment records, optionally filtered by "
                "category and/or merchant (exact, case-insensitive match — not "
                "fuzzy) and/or the last N days. Use this instead of counting "
                "retrieved examples: retrieval only ever shows a sample."
            ),
            args_model=CountTransactionsArgs,
            fn=_count_transactions,
        ),
        Tool(
            name="category_breakdown",
            description=(
                "Every category with its exact record count, largest first, "
                "optionally limited to the last N days. The whole distribution "
                "— not a top-k sample. Note: amounts are NOT captured in this "
                "system; counts are the only honest aggregate."
            ),
            args_model=CategoryBreakdownArgs,
            fn=_category_breakdown,
        ),
        Tool(
            name="find_transactions",
            description=(
                "Exhaustive exact-match listing (case-insensitive) by merchant "
                "and/or category, newest first, up to `limit` (max 20). Use for "
                "'list everything from X' — retrieval's similarity floor would "
                "silently drop rows."
            ),
            args_model=FindTransactionsArgs,
            fn=_find_transactions,
        ),
        Tool(
            name="list_policy_docs",
            description=(
                "Inventory of the policy corpus: every ingested rulebook's "
                "doc_id, title and chunk count. Use for 'what policies do you "
                "have' — similarity search cannot report extent or absence."
            ),
            args_model=ListPolicyDocsArgs,
            fn=_list_policy_docs,
        ),
    )
}


def catalog_block() -> str:
    """The tool catalog as prompt text. Rendered from the registry so
    the model's menu and the executor's whitelist CANNOT drift — one
    source, two views."""
    lines = [
        "Available tools (request one with action='tool_call'; results come back as data):"
    ]
    for tool in TOOL_REGISTRY.values():
        schema = tool.args_model.model_json_schema().get("properties", {})
        arg_names = ", ".join(schema.keys()) if schema else "(no arguments)"
        lines.append(f"  - {tool.name}({arg_names}): {tool.description}")
    return "\n".join(lines)


def execute_tool(db: Session, tool_name: str, arguments: dict | None) -> ToolOutcome:
    """The ONLY door to tool execution. Whitelist → validate → run;
    every failure is an observation (`ok=False`), never an exception —
    the loop decides what to do with it, the chat never dies for it.
    """
    tool = TOOL_REGISTRY.get(tool_name)
    if tool is None:
        # Name the real menu in the error — the model recovers best
        # when the observation says what IS available, and there is
        # nothing secret about the whitelist's names.
        return ToolOutcome(
            tool_name=tool_name,
            ok=False,
            result={
                "error": f"unknown tool '{tool_name}'",
                "available": sorted(TOOL_REGISTRY.keys()),
            },
        )

    try:
        args = tool.args_model.model_validate(arguments or {})
    except ValidationError as exc:
        return ToolOutcome(
            tool_name=tool_name,
            ok=False,
            result={"error": f"invalid arguments: {exc.errors(include_url=False)}"},
        )

    try:
        result = tool.fn(db, args)
    except Exception as exc:  # noqa: BLE001 - observation, not crash (degrade-not-fail)
        logger.warning("tool_execution_failed tool=%s error=%s", tool_name, exc)
        return ToolOutcome(
            tool_name=tool_name,
            ok=False,
            result={"error": f"tool execution failed: {type(exc).__name__}"},
        )

    return ToolOutcome(tool_name=tool_name, ok=True, result=result)
