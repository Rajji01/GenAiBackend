"""
P3 Day 4 tests — chat_service.answer_message run for real, LLM
boundary mocked at chat_service._client.create.

Covers:
- retrieval → prompt build → LLM call → earned citations overwrite
- LLM-invented cited_* get overwritten from ground truth (parallel
  to P2 D5's `test_llm_provided_citations_are_overwritten_not_appended`)
- degrade path: embed fails → chat still runs with empty context,
  empty cited_* lists (session-level degrade, not request-level fail)
- memory cap: last N turns get into the prompt; older ones stay in
  DB but don't get resent

Not integration through TestClient — the route wrapper is covered
in tests/test_chat_api.py. These tests hit the service function
directly for tighter assertions on the prompt shape + citation
overwrite behavior.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from narration_enrichment import chat_service
from narration_enrichment.chat_service import _ChatLLMReply
from narration_enrichment.db import (
    Base,
    ChatSession,
    ChatTurn,
    EnrichmentRecord,
    PolicyChunk,
    PolicyDoc,
    append_chat_turn,
    create_chat_session,
    insert_api_key,
)
from narration_enrichment import auth


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


FAKE_EMBEDDING = [0.1] * 8


def _seed_session(db, api_key_hash: str = None) -> str:
    if api_key_hash is None:
        raw = auth.generate_raw_key()
        api_key_hash = auth.hash_key(raw)
        insert_api_key(db, key_hash=api_key_hash, label="chat-llm-test")
    session_id = "test-session-uuid"
    create_chat_session(db, session_id=session_id, api_key_hash=api_key_hash)
    # Simulate the route having just persisted the user turn
    # BEFORE calling answer_message.
    append_chat_turn(db, session_id=session_id, role="user", content="what about food?")
    return session_id


def _seed_matching_enrichment(db, embedding=None, merchant="Swiggy",
                              category="food_delivery"):
    """Insert one past enrichment whose embedding matches
    FAKE_EMBEDDING so it clears the retrieval floor."""
    if embedding is None:
        embedding = FAKE_EMBEDDING
    rec = EnrichmentRecord(
        narration=f"UPI/.../{merchant}/Payment",
        merchant=merchant,
        category=category,
        transaction_type="UPI",
        confidence=0.9,
        embedding=json.dumps(embedding),
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def _seed_matching_policy_chunk(db, doc_id="mm_v1", chunk_index=0,
                                content="SWIGGY -> food_delivery"):
    if not db.query(PolicyDoc).filter(PolicyDoc.doc_id == doc_id).first():
        db.add(PolicyDoc(doc_id=doc_id, title="t", checksum="c", source_uri=None))
    chunk = PolicyChunk(
        doc_id=doc_id, chunk_index=chunk_index, content=content,
        embedding=json.dumps(FAKE_EMBEDDING),
    )
    db.add(chunk)
    db.commit()
    db.refresh(chunk)
    return chunk


# ---------------------------------------------------------------------------
# Happy path — grounding + earned citations
# ---------------------------------------------------------------------------


def test_answer_message_uses_retrieved_enrichments_as_evidence(db_session):
    session_id = _seed_session(db_session)
    enrichment = _seed_matching_enrichment(db_session, merchant="Swiggy")

    # Mock the embed boundary + the LLM call. The LLM returns any
    # answer; what matters is that the retrieved evidence lands in
    # the prompt and the response carries the retrieved id as a
    # ground-truth citation.
    llm_reply = _ChatLLMReply(
        answer="You spent on Swiggy.",
        cited_enrichment_ids=[999],   # hallucinated — should be overwritten
        cited_policy_chunk_ids=[999],
    )
    with patch(
        "narration_enrichment.chat_service.rag.embed_text",
        return_value=FAKE_EMBEDDING,
    ), patch(
        "narration_enrichment.chat_service._client.create",
        return_value=llm_reply,
    ) as mock_create:

        reply = chat_service.answer_message(
            db_session, session_id=session_id, user_message="what about food?"
        )

    # 1. Prompt actually contained the retrieved record
    prompt = mock_create.call_args.kwargs["messages"][0]["content"]
    assert f"id={enrichment.id}" in prompt
    assert "Swiggy" in prompt

    # 2. cited_enrichment_ids comes from RETRIEVAL, not from what
    #    the LLM claimed to cite. This is the earned-citations rule.
    assert reply.cited_enrichment_ids == [enrichment.id]
    assert reply.cited_policy_chunk_ids == []


def test_llm_provided_citations_get_overwritten_from_ground_truth(db_session):
    """The P3 counterpart to P2 D5's regression test. If a future
    change to chat_service accidentally lets the LLM's cited_*
    fields pass through, this test catches it -- that would be a
    hallucination class silently slipping into prod."""
    session_id = _seed_session(db_session)
    enrichment = _seed_matching_enrichment(db_session)
    chunk = _seed_matching_policy_chunk(db_session)

    hallucinated_reply = _ChatLLMReply(
        answer="I cited some hallucinated records.",
        cited_enrichment_ids=[9999, 8888],  # neither exists
        cited_policy_chunk_ids=[7777],      # neither exists
    )
    with patch(
        "narration_enrichment.chat_service.rag.embed_text",
        return_value=FAKE_EMBEDDING,
    ), patch(
        "narration_enrichment.chat_service._client.create",
        return_value=hallucinated_reply,
    ):
        reply = chat_service.answer_message(
            db_session, session_id=session_id, user_message="what about food?"
        )

    # The LLM's hallucinated ids are GONE. Ground truth wins.
    assert reply.cited_enrichment_ids == [enrichment.id]
    assert reply.cited_policy_chunk_ids == [chunk.id]


def test_assistant_turn_persists_with_ground_truth_citation_snapshot(db_session):
    session_id = _seed_session(db_session)
    enrichment = _seed_matching_enrichment(db_session)

    with patch(
        "narration_enrichment.chat_service.rag.embed_text",
        return_value=FAKE_EMBEDDING,
    ), patch(
        "narration_enrichment.chat_service._client.create",
        return_value=_ChatLLMReply(answer="ok", cited_enrichment_ids=[], cited_policy_chunk_ids=[]),
    ):
        chat_service.answer_message(
            db_session, session_id=session_id, user_message="what about food?"
        )

    # Assistant turn row has retrieved_enrichment_ids populated
    # with the SAME ground-truth list that went into the response.
    # This is the audit-trail invariant: an ops query "what did the
    # assistant use to answer turn X" is trivially provably correct.
    turn = (
        db_session.query(ChatTurn)
        .filter(ChatTurn.session_id == session_id, ChatTurn.role == "assistant")
        .one()
    )
    assert json.loads(turn.retrieved_enrichment_ids) == [enrichment.id]


# ---------------------------------------------------------------------------
# Memory cap
# ---------------------------------------------------------------------------


def test_memory_cap_only_last_N_turns_reach_the_prompt(db_session):
    session_id = _seed_session(db_session)   # already has one user turn
    # Seed 4 more user + assistant pairs so we have 9 total (with
    # the just-inserted "what about food?" being turn #1). N=6 =>
    # only the last 5 PRIOR turns (memory_turns) end up in the
    # prompt (the current user message is passed separately).
    for i in range(4):
        append_chat_turn(db_session, session_id=session_id, role="user",
                         content=f"old-question-{i}")
        append_chat_turn(db_session, session_id=session_id, role="assistant",
                         content=f"old-answer-{i}")
    # Add a fresh user turn -- this is the current message the
    # route just persisted before calling answer_message.
    append_chat_turn(db_session, session_id=session_id, role="user", content="latest?")

    with patch(
        "narration_enrichment.chat_service.rag.embed_text",
        return_value=FAKE_EMBEDDING,
    ), patch(
        "narration_enrichment.chat_service._client.create",
        return_value=_ChatLLMReply(answer="ok", cited_enrichment_ids=[], cited_policy_chunk_ids=[]),
    ) as mock_create:
        chat_service.answer_message(
            db_session, session_id=session_id, user_message="latest?"
        )

    prompt = mock_create.call_args.kwargs["messages"][0]["content"]
    # The very first user turn (the one _seed_session added, well
    # outside the last-6 window) MUST NOT appear in the prompt.
    assert "what about food?" not in prompt
    # But the most recent old-answer DID appear.
    assert "old-answer-3" in prompt


# ---------------------------------------------------------------------------
# Degrade path — embed failure doesn't kill the chat
# ---------------------------------------------------------------------------


def test_embed_failure_degrades_to_empty_context_but_chat_still_runs(db_session):
    session_id = _seed_session(db_session)
    _seed_matching_enrichment(db_session)   # would match if retrieval worked

    with patch(
        "narration_enrichment.chat_service.rag.embed_text",
        side_effect=RuntimeError("embedding provider down"),
    ), patch(
        "narration_enrichment.chat_service._client.create",
        return_value=_ChatLLMReply(
            answer="I have no retrieved records for this question.",
            cited_enrichment_ids=[], cited_policy_chunk_ids=[],
        ),
    ) as mock_create:

        reply = chat_service.answer_message(
            db_session, session_id=session_id, user_message="what about food?"
        )

    # 1. Chat still returned successfully -- no exception raised.
    assert reply.answer.startswith("I have")
    # 2. Prompt tells the model context was retrieved-then-failed.
    prompt = mock_create.call_args.kwargs["messages"][0]["content"]
    assert "No matching transactions were retrieved" in prompt
    # 3. cited_* is empty because retrieval empty -- ground truth
    #    wins even in the degrade path.
    assert reply.cited_enrichment_ids == []
    assert reply.cited_policy_chunk_ids == []
