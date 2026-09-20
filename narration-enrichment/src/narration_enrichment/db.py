"""
Persistence layer.

Week 1 was stateless: every /enrich call was answered and forgotten. Real
bank-statement processing needs the results to still exist after the
request is over — for a batch summary, for later lookup, for anything
that isn't "read it once off the wire." This is that: one table, one save
function, one list function.
"""

import json
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    func,
)
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker

from narration_enrichment.config import get_settings
from narration_enrichment.models import TransactionEnrichment

Base = declarative_base()


class EnrichmentRecord(Base):
    __tablename__ = "enrichment_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    narration = Column(String, nullable=False)
    merchant = Column(String, nullable=False)
    category = Column(String, nullable=False)
    transaction_type = Column(String, nullable=False)
    confidence = Column(Float, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    # Week 3 (RAG): the narration's embedding, JSON-encoded — SQLite has no
    # native vector type, and a JSON text column is the simplest thing that
    # works at this scale (a handful to a few thousand rows). A real
    # production-scale version would reach for a vector index; this
    # project's actual row count doesn't justify one yet.
    embedding = Column(String, nullable=True)


class PolicyDoc(Base):
    """P2 — one row per ingested policy document.

    `doc_id` is caller-chosen and stable across re-ingests: a
    re-upload of the same doc with the same id replaces the chunk
    set atomically (see policy_ingest service, Day 3). `checksum` is
    the SHA-256 of the raw text — a re-ingest with the same checksum
    returns "unchanged", no embedding work spent. `source_uri` is the
    S3 URI of the raw doc (Day 4); nullable for now so Day 2's tests
    can seed rows before S3 wiring lands.
    """

    __tablename__ = "policy_docs"

    doc_id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    source_uri = Column(String, nullable=True)
    checksum = Column(String, nullable=False)
    ingested_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    chunks = relationship(
        "PolicyChunk",
        back_populates="doc",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class PolicyChunk(Base):
    """P2 — one row per chunk of a policy doc, with its embedding.

    Chunks + embeddings are a *cache* rebuildable from the raw doc in
    S3 (P2_DESIGN.md §4). Deleting a PolicyDoc cascades and removes
    all its chunks — atomic re-ingest depends on that cascade
    behaving as advertised, which is why the relationship above sets
    `cascade="all, delete-orphan"` and `passive_deletes=True`
    together (the second one is what lets the DB do the delete
    rather than SQLAlchemy pre-loading every chunk into the session
    just to mark it deleted).

    (doc_id, chunk_index) is unique — a re-ingest that produces the
    same chunk_index twice would be a chunker bug worth catching at
    the boundary.
    """

    __tablename__ = "policy_chunks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    doc_id = Column(
        String,
        ForeignKey("policy_docs.doc_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index = Column(Integer, nullable=False)
    content = Column(String, nullable=False)
    # Same JSON-encoded shape as EnrichmentRecord.embedding — same
    # rag.py cosine code reads both. Kept nullable so a failed embed
    # can be repaired later without a schema change; the ingest
    # service refuses to persist a chunk with a NULL embedding today,
    # but a future backfill flow might.
    embedding = Column(String, nullable=True)
    embedded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    doc = relationship("PolicyDoc", back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("doc_id", "chunk_index", name="uq_policy_chunks_doc_index"),
    )


_settings = get_settings()
_connect_args = {"check_same_thread": False} if _settings.database_url.startswith("sqlite") else {}
engine = create_engine(_settings.database_url, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

# No migration tool here on purpose — this is the SQLite equivalent of
# ddl-auto=update, acceptable at this scale. The Java project's lesson
# (Flyway over ddl-auto) still applies the moment this needs to survive a
# real schema change without dropping data.
Base.metadata.create_all(engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def save_enrichment(
    db: Session,
    narration: str,
    result: TransactionEnrichment,
    embedding: list[float] | None = None,
) -> EnrichmentRecord:
    record = EnrichmentRecord(
        narration=narration,
        merchant=result.merchant,
        category=result.category,
        transaction_type=result.transaction_type,
        confidence=result.confidence,
        embedding=json.dumps(embedding) if embedding is not None else None,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def list_enrichments(db: Session, limit: int = 20, offset: int = 0) -> list[EnrichmentRecord]:
    return (
        db.query(EnrichmentRecord)
        .order_by(EnrichmentRecord.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def list_records_with_embeddings(db: Session) -> list[EnrichmentRecord]:
    # The RAG knowledge base: every past enrichment that has an embedding
    # to compare against. No LIMIT here on purpose at this project's scale
    # — see rag.py's own note about where that stops being true.
    return db.query(EnrichmentRecord).filter(EnrichmentRecord.embedding.isnot(None)).all()


def get_category_counts(db: Session) -> list[tuple[str, int]]:
    # GROUP BY in the database, not "fetch everything and Counter() it in
    # Python" — the aggregation belongs where the data lives, and this
    # scales to however many rows exist without pulling them all into
    # memory just to count them.
    return (
        db.query(EnrichmentRecord.category, func.count(EnrichmentRecord.id))
        .group_by(EnrichmentRecord.category)
        .order_by(func.count(EnrichmentRecord.id).desc())
        .all()
    )


def get_total_and_average_confidence(db: Session) -> tuple[int, float | None]:
    total = db.query(func.count(EnrichmentRecord.id)).scalar()
    # AVG over zero rows is SQL NULL, not 0 — surfacing that as None
    # rather than a misleading 0.0 average with nothing behind it.
    average_confidence = db.query(func.avg(EnrichmentRecord.confidence)).scalar()
    return total, average_confidence


# ---------------------------------------------------------------------------
# P2 — policy docs + chunks
# ---------------------------------------------------------------------------


def get_policy_doc(db: Session, doc_id: str) -> PolicyDoc | None:
    return db.query(PolicyDoc).filter(PolicyDoc.doc_id == doc_id).one_or_none()


def list_policy_docs(db: Session) -> list[tuple[PolicyDoc, int]]:
    """Every ingested policy doc, paired with its chunk count.

    One aggregate query, GROUP BY in the DB — same rule as
    get_category_counts: aggregation belongs where the data lives.
    LEFT OUTER JOIN so a doc that somehow has zero chunks (should
    never happen post-ingest, but we don't hide the state) still
    shows up with count=0.
    """
    rows = (
        db.query(PolicyDoc, func.count(PolicyChunk.id))
        .outerjoin(PolicyChunk, PolicyChunk.doc_id == PolicyDoc.doc_id)
        .group_by(PolicyDoc.doc_id)
        .order_by(PolicyDoc.ingested_at.desc())
        .all()
    )
    return [(doc, count or 0) for doc, count in rows]


def upsert_policy_doc_with_chunks(
    db: Session,
    *,
    doc_id: str,
    title: str,
    checksum: str,
    source_uri: str | None,
    chunks: list[tuple[int, str, list[float]]],
) -> PolicyDoc:
    """Atomic replace of a doc + its chunks.

    Called by the ingest service (Day 3). The whole thing runs inside
    ONE commit — a concurrent /enrich that reads policy_chunks
    mid-re-ingest either sees the old chunk set or the new, never a
    half-swapped state. This is what earns the citation contract at
    read time (P2_DESIGN.md §7): the read path can trust that the
    chunks it sees belong to a single coherent version of the doc.

    `chunks` is a list of (chunk_index, content, embedding). The
    embedding is stored JSON-encoded to match the read path in
    rag.py's cosine loop over both tables.
    """
    existing = get_policy_doc(db, doc_id)
    if existing is not None:
        # cascade="all, delete-orphan" on PolicyDoc.chunks would
        # remove the chunk rows when the doc is deleted, but here we
        # want to KEEP the doc row (same PK, replace metadata + new
        # chunks). Explicit delete of just the chunk rows keeps the
        # transaction one commit and avoids re-INSERT/PK-collision on
        # the doc row.
        db.query(PolicyChunk).filter(PolicyChunk.doc_id == doc_id).delete(
            synchronize_session=False
        )
        existing.title = title
        existing.checksum = checksum
        existing.source_uri = source_uri
        existing.ingested_at = datetime.now(timezone.utc)
        doc = existing
    else:
        doc = PolicyDoc(
            doc_id=doc_id,
            title=title,
            source_uri=source_uri,
            checksum=checksum,
        )
        db.add(doc)

    for chunk_index, content, embedding in chunks:
        db.add(
            PolicyChunk(
                doc_id=doc_id,
                chunk_index=chunk_index,
                content=content,
                embedding=json.dumps(embedding),
            )
        )

    db.commit()
    db.refresh(doc)
    return doc


def delete_policy_doc(db: Session, doc_id: str) -> bool:
    """Idempotent delete — returns True if a row was removed, False if
    the doc didn't exist. Chunks cascade automatically via the FK.
    """
    doc = get_policy_doc(db, doc_id)
    if doc is None:
        return False
    db.delete(doc)
    db.commit()
    return True


def list_policy_chunks_with_embeddings(db: Session) -> list[PolicyChunk]:
    """The read path for policy-side RAG.

    Same shape as list_records_with_embeddings (past-narration side):
    every chunk that has an embedding, no LIMIT at this project's
    scale. rag.py's cosine loop consumes the JSON-encoded embedding
    column the same way it consumes EnrichmentRecord.embedding.
    """
    return db.query(PolicyChunk).filter(PolicyChunk.embedding.isnot(None)).all()


# ---------------------------------------------------------------------------
# P3 Day 2 — API keys for the /chat/* routes
# ---------------------------------------------------------------------------


class ApiKey(Base):
    """One row per issued API key. key_hash is the SHA-256 of the
    raw key — the DB never stores the raw material. See
    `auth.hash_key` for the hash function used both at insert and at
    verify time; a bug in one is a bug in both, which is intentional
    (immediate detection instead of drift).

    `label` is human-readable (e.g. "rajat-laptop") so an audit query
    like "which keys have been idle for 90 days" is trivially
    joinable to a real person or machine. `last_used_at` starts
    NULL and is stamped on every successful auth — used by the same
    audit path to spot stale credentials that should be revoked.
    """

    __tablename__ = "api_keys"

    key_hash = Column(String, primary_key=True)
    label = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    last_used_at = Column(DateTime, nullable=True)


def insert_api_key(db: Session, *, key_hash: str, label: str) -> ApiKey:
    """Only ever called from create_api_key.py (the CLI utility).
    Kept in the repo layer so tests can round-trip inserts +
    lookups against the same seam the CLI uses, no code duplication.
    """
    row = ApiKey(key_hash=key_hash, label=label)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# P3 Day 3 — chat_sessions + chat_turns
# ---------------------------------------------------------------------------


class ChatSession(Base):
    """One row per chat session (a conversation held with one API
    key). id is a UUIDv4 string — exposed in URL paths, so an
    autoincrement int would be enumerable and let an attacker guess
    valid session ids. 122 bits of unguessable state gets rid of
    that class of attack.

    api_key_hash FKs to api_keys.key_hash so ownership is durable
    across key rotations (the row itself carries the identity, not
    a mutable owner pointer).
    """

    __tablename__ = "chat_sessions"

    id = Column(String, primary_key=True)
    api_key_hash = Column(
        String,
        ForeignKey("api_keys.key_hash", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    last_active_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    turns = relationship(
        "ChatTurn",
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ChatTurn.id",
    )


class ChatTurn(Base):
    """One row per user or assistant utterance in a session.
    Ordered by autoincrement id — that's what the "last N turns"
    memory cap iterates over in reverse for the LLM prompt (Day 4).

    retrieved_enrichment_ids + retrieved_policy_chunk_ids are JSON
    text (SQLite has no native array type). Populated only on
    assistant turns, only from GROUND TRUTH retrieval — the earned
    citations rule from P2 §6, applied to chat.
    """

    __tablename__ = "chat_turns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(
        String,
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # CHECK constraint enforces the enum at the DB level so a bug
    # in one of the write paths can't slip through with a nonsense
    # role like "system" or an empty string.
    role = Column(String, nullable=False)
    content = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    retrieved_enrichment_ids = Column(String, nullable=True)
    retrieved_policy_chunk_ids = Column(String, nullable=True)

    session = relationship("ChatSession", back_populates="turns")

    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="ck_chat_turns_role"),
    )


def create_chat_session(db: Session, *, session_id: str, api_key_hash: str) -> ChatSession:
    row = ChatSession(id=session_id, api_key_hash=api_key_hash)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_chat_session_owned_by(
    db: Session, *, session_id: str, api_key_hash: str
) -> ChatSession | None:
    """Fetch a session ONLY if it's owned by the given key. Returns
    None for both 'no such session' and 'session owned by a
    different key' — the route maps both to 404 with the same body,
    per the existence-hiding contract in P3_DESIGN §8.
    """
    return (
        db.query(ChatSession)
        .filter(ChatSession.id == session_id)
        .filter(ChatSession.api_key_hash == api_key_hash)
        .one_or_none()
    )


def append_chat_turn(
    db: Session,
    *,
    session_id: str,
    role: str,
    content: str,
    retrieved_enrichment_ids: str | None = None,
    retrieved_policy_chunk_ids: str | None = None,
) -> ChatTurn:
    """Append a turn + update the session's last_active_at in one
    commit — a concurrent /chat/{id}/message reader either sees
    both the new turn AND the fresh last_active_at, or neither.
    """
    turn = ChatTurn(
        session_id=session_id,
        role=role,
        content=content,
        retrieved_enrichment_ids=retrieved_enrichment_ids,
        retrieved_policy_chunk_ids=retrieved_policy_chunk_ids,
    )
    db.add(turn)
    # Bump last_active_at atomically with the turn insert.
    session = db.query(ChatSession).filter(ChatSession.id == session_id).one()
    session.last_active_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(turn)
    return turn


def list_chat_turns(db: Session, *, session_id: str) -> list[ChatTurn]:
    """Every turn in the session, oldest first. Used by GET
    /chat/{id} for the whole history AND by chat_service (Day 4)
    which slices to the last N turns for the LLM prompt."""
    return (
        db.query(ChatTurn)
        .filter(ChatTurn.session_id == session_id)
        .order_by(ChatTurn.id.asc())
        .all()
    )


def delete_chat_session(db: Session, *, session_id: str, api_key_hash: str) -> bool:
    """Idempotent delete. Returns True if a row was removed under
    the caller's key, False if either the session didn't exist or
    it belonged to someone else — the route returns 204 in both
    cases so an attacker can't distinguish them.
    """
    session = get_chat_session_owned_by(
        db, session_id=session_id, api_key_hash=api_key_hash
    )
    if session is None:
        return False
    db.delete(session)      # cascades to chat_turns via FK
    db.commit()
    return True
