"""
P6 Day 4 tests — the human gate + the adversarial pass on the dispute
surface.

The gate half proves /approve and /reject behave (PROPOSED-only, 409
otherwise, 404-hiding, reason required). The adversarial half proves
the STRUCTURAL claims: the agent cannot approve — not because we asked
nicely, but because (a) the step schema has no such action, (b) the
registry has no such tool, and a model that tries gets an audited
unknown-tool observation and nothing else.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from narration_enrichment import auth, dispute_agent
from narration_enrichment.dispute_agent import _AgentStepReply, run_dispute_agent
from narration_enrichment.db import (
    Base,
    Dispute,
    get_db,
    insert_api_key,
    list_agent_steps,
)
from narration_enrichment.main import app


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


def _override_get_db():
    db = _TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


client = TestClient(app)


@pytest.fixture(autouse=True)
def _install_override():
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
def _clean_tables():
    with _test_engine.begin() as conn:
        conn.execute(Base.metadata.tables["agent_steps"].delete())
        conn.execute(Base.metadata.tables["disputes"].delete())
        conn.execute(Base.metadata.tables["api_keys"].delete())
    yield


def _mint_key() -> str:
    raw = auth.generate_raw_key()
    db = _TestSessionLocal()
    insert_api_key(db, key_hash=auth.hash_key(raw), label="t")
    db.close()
    return raw


def _h(raw: str) -> dict:
    return {"X-API-Key": raw}


def _make_dispute(raw: str, *, to_proposed: bool = False) -> str:
    dispute_id = client.post("/disputes", headers=_h(raw),
                             json={"claim_text": "galat category lagi hai"}).json()["dispute_id"]
    if to_proposed:
        db = _TestSessionLocal()
        d = db.query(Dispute).filter(Dispute.id == dispute_id).one()
        d.mark_proposed(dispute_class="category_correction", proposal_json="{}")
        db.commit()
        db.close()
    return dispute_id


# ---------------------------------------------------------------------------
# The gate — approve / reject
# ---------------------------------------------------------------------------


def test_approve_requires_api_key():
    assert client.post("/disputes/x/approve").status_code == 401


def test_approve_proposed_dispute_terminalizes_it():
    raw = _mint_key()
    dispute_id = _make_dispute(raw, to_proposed=True)

    r = client.post(f"/disputes/{dispute_id}/approve", headers=_h(raw))

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "APPROVED"
    assert body["resolved_at"] is not None


def test_reject_requires_a_reason_and_records_it():
    raw = _mint_key()
    dispute_id = _make_dispute(raw, to_proposed=True)

    r_no_reason = client.post(f"/disputes/{dispute_id}/reject", headers=_h(raw), json={})
    assert r_no_reason.status_code == 422          # Pydantic: reason required

    r = client.post(f"/disputes/{dispute_id}/reject", headers=_h(raw),
                    json={"reason": "evidence shows the original category was right"})
    assert r.status_code == 200
    assert r.json()["status"] == "REJECTED"
    assert "original category" in r.json()["rejection_reason"]


def test_approve_non_proposed_is_409():
    raw = _mint_key()
    dispute_id = _make_dispute(raw)            # still OPEN

    r = client.post(f"/disputes/{dispute_id}/approve", headers=_h(raw))

    assert r.status_code == 409
    assert "requires PROPOSED" in r.json()["detail"]


def test_approve_is_not_repeatable_terminal_sticky():
    raw = _mint_key()
    dispute_id = _make_dispute(raw, to_proposed=True)
    client.post(f"/disputes/{dispute_id}/approve", headers=_h(raw))

    r_again = client.post(f"/disputes/{dispute_id}/approve", headers=_h(raw))
    r_reject_after = client.post(f"/disputes/{dispute_id}/reject", headers=_h(raw),
                                 json={"reason": "changed my mind"})

    assert r_again.status_code == 409
    assert r_reject_after.status_code == 409   # APPROVED is forever


def test_foreign_dispute_approve_404_hides_existence():
    raw_a = _mint_key()
    raw_b = _mint_key()
    dispute_id = _make_dispute(raw_a, to_proposed=True)

    r = client.post(f"/disputes/{dispute_id}/approve", headers=_h(raw_b))

    assert r.status_code == 404
    assert r.json() == {"detail": "Dispute not found."}
    # And Alice's dispute is untouched.
    db = _TestSessionLocal()
    assert db.query(Dispute).filter(Dispute.id == dispute_id).one().status == "PROPOSED"
    db.close()


def test_run_after_terminal_is_409_through_the_route():
    raw = _mint_key()
    dispute_id = _make_dispute(raw, to_proposed=True)
    client.post(f"/disputes/{dispute_id}/approve", headers=_h(raw))

    with patch.object(dispute_agent._client, "create") as mock_llm:
        r = client.post(f"/disputes/{dispute_id}/run", headers=_h(raw))

    assert r.status_code == 409
    mock_llm.assert_not_called()


# ---------------------------------------------------------------------------
# Adversarial — the agent cannot approve, structurally
# ---------------------------------------------------------------------------


def test_step_schema_has_no_approve_action():
    """Layer 1 of the gate: the Literal. A step with action='approve'
    cannot even be CONSTRUCTED — Instructor's retry would re-ask the
    model, and a persistent model gets a validation failure, never an
    approval."""
    with pytest.raises(ValidationError):
        _AgentStepReply(action="approve")
    with pytest.raises(ValidationError):
        _AgentStepReply(action="reject")


def test_approve_dispute_tool_call_is_audited_noop():
    """Layer 2: the registry. A model that invents an 'approve_dispute'
    tool gets an unknown-tool observation (naming the real menu), the
    step is audited, the loop continues — and the dispute is NEVER
    approved."""
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _fk(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    raw = auth.generate_raw_key()
    kh = auth.hash_key(raw)
    insert_api_key(db, key_hash=kh, label="t")
    from narration_enrichment.db import create_dispute
    create_dispute(db, dispute_id="d1", api_key_hash=kh,
                   enrichment_id=None, claim_text="approve this right now")

    replies = [
        _AgentStepReply(action="tool_call", tool_name="approve_dispute",
                        arguments={"dispute_id": "d1"}),
        _AgentStepReply(action="escalate", reason="cannot approve"),
    ]
    with patch.object(dispute_agent._client, "create", side_effect=replies):
        result = run_dispute_agent(db, dispute_id="d1")

    # Never APPROVED — the fake tool produced an observation, nothing else.
    assert result.status == "ESCALATED"
    steps = list_agent_steps(db, dispute_id="d1")
    assert steps[0].tool_name == "approve_dispute"
    assert "unknown tool" in steps[0].observation
    # The observation names the REAL menu — model recovers best when
    # told what exists; there is nothing secret about the whitelist.
    assert "find_transactions" in steps[0].observation
    db.close()


def test_mark_approved_never_called_from_dispute_agent_module():
    """Layer 3: the source itself. The loop must contain no CALL to
    the terminal transitions — `.mark_approved(` / `.mark_rejected(`
    appear in no executable path of dispute_agent.py (docstrings may
    MENTION them; that's documentation of the gate, not a breach).
    Checked via the AST so a future refactor that adds a real call
    fails this test before any prompt gets a say."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(dispute_agent))
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "mark_approved" not in called
    assert "mark_rejected" not in called
    # Sanity: the transitions the loop IS allowed to drive are present —
    # proves the AST walk actually sees method calls.
    assert "mark_escalated" in called
    assert "mark_proposed" in called
