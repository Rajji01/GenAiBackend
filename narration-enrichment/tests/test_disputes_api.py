"""
P6 Day 2 tests — dispute state machine (unit) + CRUD routes (integration).

No agent, no LLM anywhere in this file — Day 2 is plumbing. Same
harness pattern as test_chat_api.py: real main.app through TestClient,
in-memory SQLite + StaticPool + FK pragma, function-scoped get_db
override that restores whatever was there before.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from narration_enrichment import auth
from narration_enrichment.db import (
    AgentStep,
    Base,
    Dispute,
    append_agent_step,
    create_dispute,
    get_db,
    get_dispute_owned_by,
    insert_api_key,
    reserve_llm_call,
)
from narration_enrichment.main import app


# ---------------------------------------------------------------------------
# Unit — the state machine (named transitions only)
# ---------------------------------------------------------------------------


def _dispute(status: str = "OPEN") -> Dispute:
    d = Dispute(
        id="d-test", api_key_hash="kh", enrichment_id=None,
        claim_text="ye charge galat hai", status=status, llm_calls_used=0,
    )
    return d


def test_open_to_evidence_gathered():
    d = _dispute()
    d.mark_evidence_gathered()
    assert d.status == "EVIDENCE_GATHERED"


def test_evidence_gathered_requires_open():
    d = _dispute("PROPOSED")
    with pytest.raises(ValueError, match="requires OPEN"):
        d.mark_evidence_gathered()


def test_propose_from_open_or_evidence_gathered():
    d1 = _dispute("OPEN")
    d1.mark_proposed(dispute_class="category_correction", proposal_json="{}")
    assert d1.status == "PROPOSED"
    assert d1.dispute_class == "category_correction"

    d2 = _dispute("EVIDENCE_GATHERED")
    d2.mark_proposed(dispute_class="duplicate_charge", proposal_json="{}")
    assert d2.status == "PROPOSED"


def test_propose_rejects_unknown_class():
    d = _dispute("OPEN")
    with pytest.raises(ValueError, match="unknown dispute_class"):
        d.mark_proposed(dispute_class="not_a_class", proposal_json="{}")


def test_approve_and_reject_require_proposed():
    d = _dispute("OPEN")
    with pytest.raises(ValueError, match="requires PROPOSED"):
        d.mark_approved()
    with pytest.raises(ValueError, match="requires PROPOSED"):
        d.mark_rejected(reason="no")

    d.mark_proposed(dispute_class="unrecognized", proposal_json="{}")
    d.mark_approved()
    assert d.status == "APPROVED"
    assert d.resolved_at is not None


def test_escalate_from_any_non_terminal_but_never_from_terminal():
    for start in ("OPEN", "EVIDENCE_GATHERED", "PROPOSED"):
        d = _dispute(start)
        d.mark_escalated(reason="budget_exhausted")
        assert d.status == "ESCALATED"
        assert d.escalation_reason == "budget_exhausted"

    for terminal in ("APPROVED", "REJECTED", "ESCALATED"):
        d = _dispute(terminal)
        with pytest.raises(ValueError, match="already terminal"):
            d.mark_escalated(reason="again")


def test_terminal_states_are_sticky():
    # The whole point of named transitions: a terminal dispute cannot
    # be moved by ANY transition. (Raw status writes would bypass this
    # — which is exactly why they're not used anywhere.)
    d = _dispute("APPROVED")
    with pytest.raises(ValueError):
        d.mark_proposed(dispute_class="unrecognized", proposal_json="{}")
    with pytest.raises(ValueError):
        d.mark_escalated(reason="x")


# ---------------------------------------------------------------------------
# Unit — budget CAS (reserve_llm_call) against real SQLite
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


def _seed_key_and_dispute(db) -> str:
    raw = auth.generate_raw_key()
    kh = auth.hash_key(raw)
    insert_api_key(db, key_hash=kh, label="t")
    create_dispute(db, dispute_id="d1", api_key_hash=kh,
                   enrichment_id=None, claim_text="claim text here")
    return kh


def test_reserve_llm_call_cas_stops_exactly_at_budget(db_session):
    _seed_key_and_dispute(db_session)

    grants = [reserve_llm_call(db_session, dispute_id="d1", max_calls=3) for _ in range(5)]

    # Exactly 3 True, then False forever — the CAS predicate
    # (used < max) makes over-spend impossible even across resumes.
    assert grants == [True, True, True, False, False]
    row = db_session.query(Dispute).filter(Dispute.id == "d1").one()
    assert row.llm_calls_used == 3


def test_agent_step_unique_index_collides_loudly(db_session):
    from sqlalchemy.exc import IntegrityError
    _seed_key_and_dispute(db_session)
    append_agent_step(db_session, dispute_id="d1", step_index=0, action="tool_call")

    with pytest.raises(IntegrityError):
        # A resumed loop that miscounts step_index must fail loudly,
        # not silently double-write history.
        append_agent_step(db_session, dispute_id="d1", step_index=0, action="classify")
    db_session.rollback()


def test_deleting_dispute_cascades_steps(db_session):
    _seed_key_and_dispute(db_session)
    append_agent_step(db_session, dispute_id="d1", step_index=0, action="tool_call")

    d = db_session.query(Dispute).filter(Dispute.id == "d1").one()
    db_session.delete(d)
    db_session.commit()

    assert db_session.query(AgentStep).count() == 0


# ---------------------------------------------------------------------------
# Integration — CRUD routes through TestClient
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


def _mint_key(label: str = "t") -> str:
    raw = auth.generate_raw_key()
    db = _TestSessionLocal()
    insert_api_key(db, key_hash=auth.hash_key(raw), label=label)
    db.close()
    return raw


def _h(raw: str) -> dict:
    return {"X-API-Key": raw}


def test_all_dispute_routes_require_api_key():
    assert client.post("/disputes", json={"claim_text": "hello bhai"}).status_code == 401
    assert client.get("/disputes").status_code == 401
    assert client.get("/disputes/whatever").status_code == 401


def test_create_dispute_returns_uuid_open_row():
    raw = _mint_key()

    r = client.post("/disputes", headers=_h(raw),
                    json={"claim_text": "this UBER charge isn't mine"})

    assert r.status_code == 201
    body = r.json()
    assert len(body["dispute_id"]) == 36 and body["dispute_id"].count("-") == 4
    assert body["status"] == "OPEN"
    assert body["dispute_class"] is None
    assert body["llm_calls_used"] == 0
    assert body["claim_text"] == "this UBER charge isn't mine"


def test_create_rejects_too_short_claim():
    raw = _mint_key()
    r = client.post("/disputes", headers=_h(raw), json={"claim_text": "bad"})
    assert r.status_code == 422  # Pydantic min_length=5


def test_list_returns_only_own_disputes_newest_first():
    raw_a = _mint_key("alice")
    raw_b = _mint_key("bob")
    client.post("/disputes", headers=_h(raw_a), json={"claim_text": "alice first claim"})
    client.post("/disputes", headers=_h(raw_a), json={"claim_text": "alice second claim"})
    client.post("/disputes", headers=_h(raw_b), json={"claim_text": "bob's only claim"})

    r = client.get("/disputes", headers=_h(raw_a))

    assert r.status_code == 200
    claims = [d["claim_text"] for d in r.json()]
    # Only Alice's, newest first.
    assert claims == ["alice second claim", "alice first claim"]


def test_get_detail_includes_steps_in_order():
    raw = _mint_key()
    dispute_id = client.post("/disputes", headers=_h(raw),
                             json={"claim_text": "duplicate charge dikha"}).json()["dispute_id"]
    db = _TestSessionLocal()
    append_agent_step(db, dispute_id=dispute_id, step_index=0, action="tool_call",
                      tool_name="find_transactions", observation="2 rows")
    append_agent_step(db, dispute_id=dispute_id, step_index=1, action="classify")
    db.close()

    r = client.get(f"/disputes/{dispute_id}", headers=_h(raw))

    assert r.status_code == 200
    steps = r.json()["steps"]
    assert [s["step_index"] for s in steps] == [0, 1]
    assert steps[0]["tool_name"] == "find_transactions"


def test_missing_and_foreign_dispute_return_same_404():
    raw_a = _mint_key("alice")
    raw_b = _mint_key("bob")
    alice_id = client.post("/disputes", headers=_h(raw_a),
                           json={"claim_text": "alice ka dispute"}).json()["dispute_id"]

    r_missing = client.get("/disputes/00000000-0000-0000-0000-000000000000", headers=_h(raw_b))
    r_foreign = client.get(f"/disputes/{alice_id}", headers=_h(raw_b))

    # Existence-hiding (P3 invariant #2): byte-identical bodies.
    assert r_missing.status_code == r_foreign.status_code == 404
    assert r_missing.json() == r_foreign.json() == {"detail": "Dispute not found."}


def test_claim_text_is_trimmed_on_save():
    raw = _mint_key()
    r = client.post("/disputes", headers=_h(raw),
                    json={"claim_text": "   padded claim text   "})
    assert r.json()["claim_text"] == "padded claim text"
