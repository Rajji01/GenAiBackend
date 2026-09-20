"""
P3 Day 4 — real LLM chat integration.

Swaps the Day-3 echo stub for a grounded chat call. Every message
call builds a prompt from three sources:

  1. `last N chat_turns` — recent conversation memory (default N=6).
     Old turns are still in the DB (GET /chat/{id} returns all
     history), just not resent to the LLM every message. Cap policy
     is a token-cost thing, not a data-retention thing. See
     P3_DESIGN §4.

  2. `retrieve_similar_examples` — past enrichment records that
     cosine-match the QUESTION embedding, floor 0.65 for chat
     (looser than /enrich's 0.70 because the questions are prose,
     not narrations, and cosine is inherently a bit lower on
     dissimilar surface forms).

  3. `retrieve_policy_chunks` — same P2 function /enrich uses. Rules
     govern the assistant just as they govern the classifier.

The assistant's reply is a Pydantic `_ChatLLMReply` that Instructor
forces the model output to conform to. THEN we overwrite the
`cited_*` fields from GROUND TRUTH — the actual retrieval hits that
went into the prompt for this call. The model chooses the answer;
the service chooses the citations. Same "earned citations" rule as
P2, extended to chat.

If retrieval fails (embed provider down), the chat call still
succeeds with degraded context — the assistant is told "no records
were retrieved for this question" and answers from prior turns
only, with empty cited_* lists. Same degrade-not-fail rule that
runs through everything else in this service.
"""

from __future__ import annotations

import json
import logging
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from narration_enrichment import rag
from narration_enrichment.db import (
    ChatTurn,
    EnrichmentRecord,
    PolicyChunk,
    append_chat_turn,
    list_chat_turns,
)
from narration_enrichment.schemas import ChatReply
from narration_enrichment.service import _client, _settings, _call_llm  # noqa: F401

logger = logging.getLogger(__name__)


# How many recent turns get resent to the LLM per message. 6 =
# 3 user + 3 assistant, which is enough for "and just the delivery
# apps" to still reference "how much on food last month?" three
# messages back. Kept as a module constant, not env-driven, until
# there's a measured reason to make it configurable per deployment.
CHAT_MEMORY_MAX_TURNS = 6

# Chat retrieval floors — deliberately looser than /enrich's (which
# operates on formulaic bank narrations). Chat questions are prose;
# cosine scores inherently drop. Tunable once we have per-case
# accuracy numbers from a chat-specific eval extension (post-P3).
CHAT_MIN_SIMILARITY = 0.65
CHAT_POLICY_MIN_SIMILARITY = 0.60
CHAT_TOP_K = 3


class _ChatLLMReply(BaseModel):
    """The shape Instructor forces the LLM's output to conform to.

    NOT the response returned to the client -- the route
    (`chat_send_message` in main.py) constructs a `ChatReply` where
    cited_* come from ground-truth retrieval, not from anything the
    model wrote. That overwrite is what makes citations "earned."

    Kept private (`_` prefix) so this file's caller doesn't
    accidentally use this type where a ChatReply is expected.
    """

    answer: str = Field(
        ...,
        description=(
            "The natural-language answer. Grounded in the retrieved "
            "records only — if the retrieved records don't contain the "
            "information the user asked for, say so plainly instead of "
            "inventing transactions."
        ),
    )
    # These fields exist in the schema Instructor sees so the model
    # CAN populate them (some prompts nudge better classification
    # when the model is asked to enumerate its own reasoning). The
    # service overwrites them from ground truth before returning.
    cited_enrichment_ids: list[int] = Field(default_factory=list)
    cited_policy_chunk_ids: list[int] = Field(default_factory=list)


def _memory_block(turns: list[ChatTurn]) -> str:
    """Format the last N turns for inclusion in the prompt. Oldest
    first so the model reads the conversation in order. Empty
    string (not None) when there are no prior turns — the model's
    prompt template can safely concat this without a conditional."""
    if not turns:
        return ""
    lines = ["Conversation so far (oldest first):"]
    for t in turns:
        who = "User" if t.role == "user" else "Assistant"
        lines.append(f"  {who}: {t.content}")
    return "\n".join(lines)


def _evidence_block(matches: list[EnrichmentRecord]) -> str:
    """Retrieved past enrichments as EVIDENCE the assistant may
    reason from. Kept plain-text with one row per line — Instructor
    still sees the JSON schema of _ChatLLMReply, so the prompt just
    needs to be readable, not itself structured."""
    if not matches:
        return ""
    lines = ["Recent transactions retrieved for this question (id | merchant | category | rail | narration):"]
    for record in matches:
        lines.append(
            f"  id={record.id} | {record.merchant} | {record.category} | "
            f"{record.transaction_type} | {record.narration}"
        )
    return "\n".join(lines)


def _policy_block(scored_chunks: list[tuple[float, PolicyChunk]]) -> str:
    if not scored_chunks:
        return ""
    lines = ["Applicable policy excerpts (treat as rules):"]
    for _score, chunk in scored_chunks:
        lines.append(f"  [doc_id={chunk.doc_id}, chunk {chunk.chunk_index}]: {chunk.content}")
    return "\n".join(lines)


def _build_prompt(
    user_message: str,
    memory: str,
    evidence: str,
    policy: str,
) -> str:
    """Order chosen deliberately. System prompt at the top; memory
    then evidence then policy so the model reads context → history
    → data → rules → question, with the current question closest
    to where the response is generated (recency bias exploited)."""
    header = (
        "You are an assistant that answers questions about the user's bank "
        "transactions using ONLY the retrieved records below. If the answer "
        "isn't in the records, say so plainly — DO NOT invent transactions. "
        "Cite records by id when the answer references specific ones."
    )
    sections = [header]
    if memory:
        sections.append(memory)
    if evidence:
        sections.append(evidence)
    else:
        sections.append("(No matching transactions were retrieved for this question.)")
    if policy:
        sections.append(policy)
    sections.append(f"Current question: {user_message}")
    return "\n\n".join(sections)


def answer_message(db: Session, *, session_id: str, user_message: str) -> ChatReply:
    """The Day-4 replacement for the Day-3 echo stub. Called by the
    /chat/{session_id}/message route AFTER the user turn has been
    persisted but BEFORE the assistant turn is written — the reply
    this returns is what gets persisted as the assistant turn.

    Contract:
    - Returns a ChatReply whose `cited_*` fields are GROUND TRUTH.
    - Persists the assistant turn (with retrieved ids serialized on
      the row) inside this function -- callers do not need to
      remember to save it.
    - Never raises on retrieval failures — degrades to empty
      context (assistant told "no records retrieved") and continues.
    - Raises on LLM call failures (same shape as /enrich); the
      route maps those to 503 with Retry-After.
    """
    raw_client = None
    try:
        # Imported here (not at module top) to avoid the module-import-
        # time construction of the Instructor client during tests that
        # never call this function.
        from narration_enrichment.service import get_raw_client
        raw_client = get_raw_client()
    except Exception:  # noqa: BLE001
        # If we can't even build the client (e.g. missing key in
        # dev), fall through — retrieval will fail cleanly and the
        # LLM call will raise, which the route already maps.
        raw_client = None

    # ---- retrieval (both degrade cleanly on failure) --------------
    query_embedding: list[float] | None = None
    evidence: list[EnrichmentRecord] = []
    policy: list[tuple[float, PolicyChunk]] = []

    if raw_client is not None:
        try:
            query_embedding = rag.embed_text(
                raw_client, user_message, task_type="RETRIEVAL_QUERY"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("chat_embed_failed error=%s", exc)

    if query_embedding is not None:
        try:
            evidence = rag.find_similar_examples(
                db, query_embedding, min_similarity=CHAT_MIN_SIMILARITY, top_k=CHAT_TOP_K
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("chat_enrichment_retrieval_failed error=%s", exc)
        try:
            policy = rag.retrieve_policy_chunks(
                db, query_embedding,
                min_similarity=CHAT_POLICY_MIN_SIMILARITY,
                top_k=CHAT_TOP_K,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("chat_policy_retrieval_failed error=%s", exc)

    # ---- memory (last N turns, ignoring the just-inserted user
    #      turn since it IS the current question) -------------------
    all_turns = list_chat_turns(db, session_id=session_id)
    # The most recently inserted turn IS the current user message
    # (the route persists it before calling us). Slice it off so it
    # doesn't appear twice in the prompt.
    prior_turns = all_turns[:-1] if all_turns and all_turns[-1].role == "user" else all_turns
    memory_turns = prior_turns[-CHAT_MEMORY_MAX_TURNS:]

    # ---- build + call ---------------------------------------------
    prompt = _build_prompt(
        user_message,
        memory=_memory_block(memory_turns),
        evidence=_evidence_block(evidence),
        policy=_policy_block(policy),
    )

    logger.info(
        "chat_llm_call session_id=%s evidence_count=%d policy_count=%d memory_turns=%d",
        session_id, len(evidence), len(policy), len(memory_turns),
    )

    llm_reply: _ChatLLMReply = _client.create(
        response_model=_ChatLLMReply,
        messages=[{"role": "user", "content": prompt}],
        max_retries=_settings.max_retries,
    )

    # ---- EARN the citations (P3_DESIGN §6) ------------------------
    # Overwrite whatever the LLM said it cited with the actual
    # retrieval result. Regression-tested — the model cannot smuggle
    # a hallucinated id past this line.
    reply = ChatReply(
        answer=llm_reply.answer,
        cited_enrichment_ids=[r.id for r in evidence],
        cited_policy_chunk_ids=[c.id for _score, c in policy],
    )

    # ---- persist the assistant turn with ground-truth citation
    #      snapshot on the row (audit trail) ------------------------
    append_chat_turn(
        db,
        session_id=session_id,
        role="assistant",
        content=reply.answer,
        retrieved_enrichment_ids=json.dumps(reply.cited_enrichment_ids),
        retrieved_policy_chunk_ids=json.dumps(reply.cited_policy_chunk_ids),
    )
    return reply
