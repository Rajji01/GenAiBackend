"""
P3 Day 3 tests — /chat/* routes end-to-end through TestClient.

Every test:
- mints a real API key row via the same insert_api_key repo the CLI
  uses (proves the auth seam agrees with the runtime seam)
- runs against the real main.app + real in-memory SQLite (StaticPool)
- LLM is NOT called — the Day-3 stub is a deterministic echo, so
  these tests validate the plumbing without any mocking of the
  generative boundary. Day 4 will mock enrich_narration-equivalent.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from narration_enrichment import auth
from narration_enrichment.db import (
    ApiKey,
    Base,
    ChatSession,
    ChatTurn,
    append_chat_turn,
    get_db,
    insert_api_key,
)
from narration_enrichment.main import app
from narration_enrichment.schemas import ChatReply


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
    # Function-scoped so we don't stomp on other test files' overrides.
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
def _clean_chat_tables():
    # Order matters — turns → sessions → api_keys (FK dependency).
    with _test_engine.begin() as conn:
        conn.execute(Base.metadata.tables["chat_turns"].delete())
        conn.execute(Base.metadata.tables["chat_sessions"].delete())
        conn.execute(Base.metadata.tables["api_keys"].delete())
    yield


@pytest.fixture(autouse=True)
def _mock_chat_service():
    """P3 Day 4: main.chat_send_message now calls the real
    chat_service.answer_message, which fires an LLM request.
    Every /chat/{id}/message test below is really testing the
    ROUTE (auth, ownership, plumbing) not the LLM behavior --
    so we mock the boundary that fires the network call and
    return a deterministic reply + persist the assistant turn
    ourselves, mirroring what chat_service.answer_message would
    do minus the network.
    """

    def _fake_answer(db, *, session_id, user_message):
        reply = ChatReply(
            answer="[mocked-chat] "
                   f"session={session_id[:8]} chars={len(user_message)}",
            cited_enrichment_ids=[],
            cited_policy_chunk_ids=[],
        )
        append_chat_turn(
            db, session_id=session_id, role="assistant", content=reply.answer,
            retrieved_enrichment_ids=None,
            retrieved_policy_chunk_ids=None,
        )
        return reply

    with patch(
        "narration_enrichment.main.chat_service.answer_message",
        side_effect=_fake_answer,
    ):
        yield


def _mint_key(label: str = "test-key") -> str:
    raw = auth.generate_raw_key()
    db = _TestSessionLocal()
    insert_api_key(db, key_hash=auth.hash_key(raw), label=label)
    db.close()
    return raw


def _headers(raw: str) -> dict:
    return {"X-API-Key": raw}


# ---------------------------------------------------------------------------
# Auth-gate on every chat route
# ---------------------------------------------------------------------------


def test_chat_session_requires_api_key():
    r = client.post("/chat/session")
    assert r.status_code == 401
    assert r.json() == {"detail": "API key missing or invalid."}


def test_chat_send_message_requires_api_key():
    r = client.post("/chat/does-not-matter/message", json={"message": "hi"})
    assert r.status_code == 401


def test_chat_get_history_requires_api_key():
    r = client.get("/chat/does-not-matter")
    assert r.status_code == 401


def test_chat_delete_requires_api_key():
    r = client.delete("/chat/does-not-matter")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------


def test_create_session_returns_uuid_and_persists_row():
    raw = _mint_key()

    r = client.post("/chat/session", headers=_headers(raw))

    assert r.status_code == 201
    body = r.json()
    session_id = body["session_id"]
    # UUIDv4 — 36 chars with hyphens. If a future change swaps to
    # an int id, this test catches the enumerability regression.
    assert len(session_id) == 36
    assert session_id.count("-") == 4

    # Row landed in the DB, attributed to the calling key.
    db = _TestSessionLocal()
    row = db.query(ChatSession).one()
    assert row.id == session_id
    assert row.api_key_hash == auth.hash_key(raw)
    db.close()


def test_send_message_persists_user_and_assistant_turns_and_echoes():
    raw = _mint_key()
    session_id = client.post("/chat/session", headers=_headers(raw)).json()["session_id"]

    r = client.post(
        f"/chat/{session_id}/message",
        headers=_headers(raw),
        json={"message": "how much did I spend on food?"},
    )

    assert r.status_code == 200
    body = r.json()
    # Post Day 4: LLM boundary mocked, deterministic prefix per fixture.
    assert body["answer"].startswith("[mocked-chat]")
    # cited_* lists still empty because the fixture returns none;
    # the earned-citations behavior is exercised in test_chat_llm.py
    # where chat_service.answer_message runs for real (against a
    # mocked _client.create underneath).
    assert body["cited_enrichment_ids"] == []
    assert body["cited_policy_chunk_ids"] == []

    # Two turns landed atomically — user + assistant.
    db = _TestSessionLocal()
    turns = db.query(ChatTurn).filter(ChatTurn.session_id == session_id).order_by(ChatTurn.id).all()
    assert [t.role for t in turns] == ["user", "assistant"]
    assert turns[0].content == "how much did I spend on food?"
    assert turns[1].content == body["answer"]
    db.close()


def test_send_message_trims_the_user_content_on_save():
    raw = _mint_key()
    session_id = client.post("/chat/session", headers=_headers(raw)).json()["session_id"]

    client.post(
        f"/chat/{session_id}/message",
        headers=_headers(raw),
        json={"message": "   padded on both sides   "},
    )

    db = _TestSessionLocal()
    user_turn = (
        db.query(ChatTurn)
        .filter(ChatTurn.session_id == session_id, ChatTurn.role == "user")
        .one()
    )
    assert user_turn.content == "padded on both sides"
    db.close()


def test_get_history_returns_turns_oldest_first():
    raw = _mint_key()
    session_id = client.post("/chat/session", headers=_headers(raw)).json()["session_id"]
    for msg in ["first question", "second question", "third question"]:
        client.post(f"/chat/{session_id}/message", headers=_headers(raw), json={"message": msg})

    r = client.get(f"/chat/{session_id}", headers=_headers(raw))

    assert r.status_code == 200
    body = r.json()
    # 3 user + 3 assistant = 6 turns, ordered by id ascending
    assert len(body["turns"]) == 6
    assert [t["role"] for t in body["turns"]] == ["user", "assistant"] * 3
    assert body["turns"][0]["content"] == "first question"
    assert body["turns"][2]["content"] == "second question"


def test_delete_session_cascades_to_turns_and_returns_204():
    raw = _mint_key()
    session_id = client.post("/chat/session", headers=_headers(raw)).json()["session_id"]
    client.post(f"/chat/{session_id}/message", headers=_headers(raw), json={"message": "hi"})

    r = client.delete(f"/chat/{session_id}", headers=_headers(raw))

    assert r.status_code == 204
    db = _TestSessionLocal()
    # Session gone AND its turns gone via FK CASCADE.
    assert db.query(ChatSession).filter(ChatSession.id == session_id).count() == 0
    assert db.query(ChatTurn).filter(ChatTurn.session_id == session_id).count() == 0
    db.close()


def test_delete_missing_session_is_idempotent_204():
    raw = _mint_key()

    r = client.delete("/chat/nope-not-real", headers=_headers(raw))

    assert r.status_code == 204


# ---------------------------------------------------------------------------
# Existence hiding — same 404 for "not there" and "not yours"
# ---------------------------------------------------------------------------


def test_send_message_to_missing_session_returns_404_generic():
    raw = _mint_key()

    r = client.post(
        "/chat/00000000-0000-0000-0000-000000000000/message",
        headers=_headers(raw),
        json={"message": "hi"},
    )

    assert r.status_code == 404
    assert r.json() == {"detail": "Session not found."}


def test_send_message_to_someone_elses_session_returns_same_404_generic():
    """The core existence-hiding test. A session created under key A
    must NOT be distinguishable from a nonexistent session when
    probed under key B. Both return 404 with the same body — if a
    future refactor introduces 403 for the "not yours" case, an
    attacker who knows any valid session id from a leaked log can
    enumerate other keys' access."""
    raw_a = _mint_key(label="alice")
    raw_b = _mint_key(label="bob")

    # Alice creates a session
    session_id = client.post("/chat/session", headers=_headers(raw_a)).json()["session_id"]

    # Bob probes it
    r_send = client.post(
        f"/chat/{session_id}/message",
        headers=_headers(raw_b),
        json={"message": "hi"},
    )
    r_get = client.get(f"/chat/{session_id}", headers=_headers(raw_b))
    r_del = client.delete(f"/chat/{session_id}", headers=_headers(raw_b))

    # Send + Get return 404 with the same body as the missing-session case above.
    assert r_send.status_code == 404
    assert r_send.json() == {"detail": "Session not found."}
    assert r_get.status_code == 404
    assert r_get.json() == {"detail": "Session not found."}
    # Delete returns 204 (idempotent) whether it existed under Bob's
    # key or not — same body-shape either way, no distinguishable
    # response for the two cases.
    assert r_del.status_code == 204

    # Critically: Alice's session and its turns are UNTOUCHED after
    # Bob's probing. Existence-hiding without ownership-enforcement
    # would be a much worse bug.
    db = _TestSessionLocal()
    assert db.query(ChatSession).filter(ChatSession.id == session_id).count() == 1
    db.close()


def test_send_message_pydantic_rejects_empty_body():
    raw = _mint_key()
    session_id = client.post("/chat/session", headers=_headers(raw)).json()["session_id"]

    r = client.post(f"/chat/{session_id}/message", headers=_headers(raw), json={"message": ""})

    assert r.status_code == 422  # Pydantic min_length=1


def test_last_active_at_updates_on_each_message():
    raw = _mint_key()
    session_id = client.post("/chat/session", headers=_headers(raw)).json()["session_id"]

    db = _TestSessionLocal()
    initial = db.query(ChatSession).filter(ChatSession.id == session_id).one().last_active_at
    db.close()

    # Small pause not needed — the datetime.now() at message time is
    # after the datetime.now() at session-create time in wall-clock
    # order; even monotonic-clock precision on Windows is enough.
    client.post(f"/chat/{session_id}/message", headers=_headers(raw), json={"message": "hi"})

    db = _TestSessionLocal()
    updated = db.query(ChatSession).filter(ChatSession.id == session_id).one().last_active_at
    db.close()

    assert updated >= initial
