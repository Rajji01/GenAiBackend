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


# ---------------------------------------------------------------------------
# P3 Day 5 — eval-as-a-system (persistent run + per-case history)
# ---------------------------------------------------------------------------


class EvalRun(Base):
    """One row per eval invocation (i.e. one `python eval/run_eval.py`
    run). id is a UUID chosen at run start; started_at + finished_at
    bracket the actual measurement window; totals + a free-form
    `notes` field capture the aggregate + human tag ("post-P3-policy-
    tune", "pre-prompt-refactor").
    """

    __tablename__ = "eval_runs"

    id = Column(String, primary_key=True)
    started_at = Column(DateTime, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    model_name = Column(String, nullable=False)
    total_cases = Column(Integer, nullable=False)
    passed = Column(Integer, nullable=False)
    failed = Column(Integer, nullable=False)
    notes = Column(String, nullable=True)

    results = relationship(
        "EvalResult",
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class EvalResult(Base):
    """One row per (run, case) — the per-case outcome.

    `expected` + `actual` are JSON text so the shape can evolve
    without a schema migration; today they're the same dicts the
    JSON report file carries. `error` is populated only for
    call-failure cases (timeout / quota / provider outage) —
    reliability failures kept separate from correctness failures
    is the same rule the existing print-summary applies.
    """

    __tablename__ = "eval_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(
        String,
        ForeignKey("eval_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    case_id = Column(String, nullable=False, index=True)
    passed = Column(Integer, nullable=False)   # bool as int for CHECK
    expected = Column(String, nullable=False)
    actual = Column(String, nullable=False)
    latency_ms = Column(Integer, nullable=True)
    error = Column(String, nullable=True)

    run = relationship("EvalRun", back_populates="results")

    __table_args__ = (
        CheckConstraint("passed IN (0, 1)", name="ck_eval_results_passed_bool"),
    )


def record_eval_run(
    db: Session,
    *,
    run_id: str,
    started_at: datetime,
    finished_at: datetime,
    model_name: str,
    outcomes: list[dict],
    notes: str | None = None,
) -> EvalRun:
    """Persist one eval run + all its per-case results atomically.

    Called from `eval/run_eval.py` after the run finishes AND from
    the tests directly (the tests bypass the LLM by passing a
    hand-built outcomes list). `outcomes` uses the same dict shape
    `run_eval.compare_result` already returns, so the extension
    doesn't force a rewrite of that pipeline.
    """
    passed_count = sum(1 for o in outcomes if o.get("all_correct"))
    run = EvalRun(
        id=run_id,
        started_at=started_at,
        finished_at=finished_at,
        model_name=model_name,
        total_cases=len(outcomes),
        passed=passed_count,
        failed=len(outcomes) - passed_count,
        notes=notes,
    )
    db.add(run)

    for outcome in outcomes:
        db.add(EvalResult(
            run_id=run_id,
            case_id=outcome["id"],
            passed=1 if outcome.get("all_correct") else 0,
            expected=json.dumps(outcome.get("expected", {})),
            actual=json.dumps(outcome.get("got", {})),
            latency_ms=outcome.get("latency_ms"),
            error=outcome.get("error"),
        ))

    db.commit()
    db.refresh(run)
    return run


def list_eval_runs(db: Session, limit: int = 20) -> list[EvalRun]:
    return (
        db.query(EvalRun)
        .order_by(EvalRun.started_at.desc())
        .limit(limit)
        .all()
    )


def get_eval_history_for_case(
    db: Session, *, case_id: str, limit: int = 20
) -> list[EvalResult]:
    """Every historical result for one case, newest first. Joined
    to EvalRun for the started_at timestamp so the caller can
    render a "when did case X start failing" timeline."""
    return (
        db.query(EvalResult)
        .join(EvalRun, EvalResult.run_id == EvalRun.id)
        .filter(EvalResult.case_id == case_id)
        .order_by(EvalRun.started_at.desc())
        .limit(limit)
        .all()
    )


def get_eval_pass_rate_by_case(db: Session, limit_per_case: int = 20) -> list[tuple[str, int, int]]:
    """(case_id, passed_count, total_count) rollup across the most
    recent `limit_per_case` runs per case. GROUP BY in the DB, not
    "fetch every result and Counter() them in Python."
    """
    return (
        db.query(
            EvalResult.case_id,
            func.sum(EvalResult.passed),
            func.count(EvalResult.id),
        )
        .group_by(EvalResult.case_id)
        .order_by(EvalResult.case_id)
        .all()
    )


# ---------------------------------------------------------------------------
# P4 Day 2 — ingest_jobs (async ingestion)
# ---------------------------------------------------------------------------

# One-way status lifecycle (P4_DESIGN.md §3). Same state-machine
# discipline as payment-service's PaymentStatus — explicit terminal
# states, no transition ever runs backwards:
#   QUEUED → PROCESSING → DONE
#          ↘ FAILED (retryable) → QUEUED (re-enqueue) | DEAD (max attempts)
JOB_QUEUED = "QUEUED"
JOB_PROCESSING = "PROCESSING"
JOB_DONE = "DONE"
JOB_FAILED = "FAILED"
JOB_DEAD = "DEAD"

_JOB_STATUSES = (JOB_QUEUED, JOB_PROCESSING, JOB_DONE, JOB_FAILED, JOB_DEAD)


class IngestJob(Base):
    """One row per async ingest request. THE source of truth for the
    pipeline — the queue message carries only this row's id
    (P4_DESIGN.md §5: job row = truth, message = hint). The worker,
    the recovery sweep, and GET /jobs/{id} all read state from here,
    never from the queue.

    `id` is a UUIDv4 string because it's exposed in GET /jobs/{id} —
    same enumeration argument as ChatSession.id. `content` holds the
    raw doc text (small policy docs; an S3-pointer variant is a P4
    stretch goal, deliberately not built before something needs it —
    rule 3-7). `checksum` is computed at enqueue time so the dedup
    fast-paths never re-read content.
    """

    __tablename__ = "ingest_jobs"

    id = Column(String, primary_key=True)
    doc_id = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    content = Column(String, nullable=False)
    checksum = Column(String, nullable=False)
    source_uri = Column(String, nullable=True)
    status = Column(String, nullable=False, default=JOB_QUEUED, index=True)
    attempts = Column(Integer, nullable=False, default=0)
    error = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    __table_args__ = (
        # DB-level guard, same pattern as chat_turns.role: a typo'd
        # status string is a bug worth failing loudly on at write time,
        # not a mystery row the sweep silently never matches.
        CheckConstraint(
            "status IN ('QUEUED','PROCESSING','DONE','FAILED','DEAD')",
            name="ck_ingest_jobs_status",
        ),
    )


def create_ingest_job(
    db: Session,
    *,
    job_id: str,
    doc_id: str,
    title: str,
    content: str,
    checksum: str,
) -> IngestJob:
    job = IngestJob(
        id=job_id,
        doc_id=doc_id,
        title=title,
        content=content,
        checksum=checksum,
        status=JOB_QUEUED,
        attempts=0,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def get_ingest_job(db: Session, job_id: str) -> IngestJob | None:
    return db.query(IngestJob).filter(IngestJob.id == job_id).one_or_none()


def find_ingest_job_by_checksum(
    db: Session, *, doc_id: str, checksum: str, statuses: tuple[str, ...]
) -> IngestJob | None:
    """Newest job for this exact (doc_id, checksum) pair in one of the
    given statuses. Backs the two enqueue-time idempotency fast-paths
    (P4_DESIGN.md §6): same pair already DONE → report unchanged
    without a new job; same pair already QUEUED/PROCESSING → return
    that job instead of double-queueing identical work."""
    return (
        db.query(IngestJob)
        .filter(
            IngestJob.doc_id == doc_id,
            IngestJob.checksum == checksum,
            IngestJob.status.in_(statuses),
        )
        .order_by(IngestJob.created_at.desc())
        .limit(1)
        .one_or_none()
    )


def count_ingest_backlog(db: Session) -> int:
    """QUEUED + PROCESSING count — the number the intake valve
    compares against ingest_max_backlog (P4_DESIGN.md §8). COUNT in
    the DB, same rule as every other aggregate here."""
    return (
        db.query(func.count(IngestJob.id))
        .filter(IngestJob.status.in_((JOB_QUEUED, JOB_PROCESSING)))
        .scalar()
    ) or 0


class ToolInvocation(Base):
    """P5 Day 3 — one row per tool execution ATTEMPT (success and
    failure alike, whitelist misses included). Written by the same
    code path that executes (`chat_service`'s loop calling
    `tools.execute_tool`), so the audit cannot drift from reality —
    there is no second bookkeeping. The earned-trail counterpart of
    chat_turns.retrieved_*: the model's narrative is never the audit.
    """

    __tablename__ = "tool_invocations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(
        String,
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tool_name = Column(String, nullable=False)
    arguments_json = Column(String, nullable=False)
    result_json = Column(String, nullable=False)
    ok = Column(Integer, nullable=False)  # SQLite bool-as-int, same as EvalResult.passed
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


def record_tool_invocation(
    db: Session,
    *,
    session_id: str,
    tool_name: str,
    arguments: dict | None,
    ok: bool,
    result: dict,
) -> ToolInvocation:
    row = ToolInvocation(
        session_id=session_id,
        tool_name=tool_name,
        arguments_json=json.dumps(arguments or {}),
        result_json=json.dumps(result),
        ok=1 if ok else 0,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_tool_invocations(db: Session, *, session_id: str) -> list[ToolInvocation]:
    return (
        db.query(ToolInvocation)
        .filter(ToolInvocation.session_id == session_id)
        .order_by(ToolInvocation.id.asc())
        .all()
    )


def claim_ingest_job(db: Session, job_id: str) -> bool:
    """P4 Day 3 — the worker's compare-and-set claim.

    One UPDATE whose WHERE carries the allowed source states
    (QUEUED → first attempt, FAILED → a sweep-re-enqueued retry).
    Returns True iff exactly this call moved the row to PROCESSING.

    This is the idempotent-consumer dedup (P4_DESIGN.md §6 layer 2,
    ticketing Day-7's lesson): a message re-delivered while the job
    is already PROCESSING/DONE/DEAD matches ZERO rows — the caller
    acks and drops without touching the job. The status column plays
    the role ticketing's processed_event table played.
    """
    claimed = (
        db.query(IngestJob)
        .filter(IngestJob.id == job_id, IngestJob.status.in_((JOB_QUEUED, JOB_FAILED)))
        .update(
            {
                IngestJob.status: JOB_PROCESSING,
                IngestJob.attempts: IngestJob.attempts + 1,
                IngestJob.started_at: datetime.now(timezone.utc),
            },
            synchronize_session=False,
        )
    )
    db.commit()
    return claimed == 1


def finish_ingest_job(db: Session, job_id: str, *, status: str, error: str | None = None) -> None:
    """Terminal-or-retryable outcome write for one attempt. `status`
    is DONE, FAILED or DEAD; `error` is kept on FAILED and DEAD so an
    operator reading GET /jobs/{id} sees the last real reason, and is
    cleared on DONE (a stale error string on a succeeded job would
    read as a contradiction)."""
    db.query(IngestJob).filter(IngestJob.id == job_id).update(
        {
            IngestJob.status: status,
            IngestJob.error: error,
            IngestJob.finished_at: datetime.now(timezone.utc),
        },
        synchronize_session=False,
    )
    db.commit()


def list_ingest_jobs_by_status(db: Session, status: str) -> list[IngestJob]:
    """All jobs in one status, oldest first. The sweep's working set:
    QUEUED/PROCESSING/FAILED populations are small by construction
    (bounded by the intake valve), so fetching rows and doing the
    age arithmetic in Python sidesteps SQLite's string-typed
    datetime comparisons — the one place a SQL-side cutoff can lie
    silently about timezones."""
    return (
        db.query(IngestJob)
        .filter(IngestJob.status == status)
        .order_by(IngestJob.created_at.asc())
        .all()
    )


def count_ingest_jobs_by_status(db: Session) -> dict[str, int]:
    """Per-status rollup for GET /ops/ingest (Day 5 wires the route;
    the query lands with the table so Day 2's tests can already pin
    it). Every status appears in the result, zero included — an ops
    endpoint that omits empty states makes 'is DEAD empty or missing?'
    ambiguous."""
    rows = (
        db.query(IngestJob.status, func.count(IngestJob.id))
        .group_by(IngestJob.status)
        .all()
    )
    counts = {status: 0 for status in _JOB_STATUSES}
    counts.update({status: count for status, count in rows})
    return counts


# ---------------------------------------------------------------------------
# P6 Day 2 — disputes + agent steps (agentic workflow)
# ---------------------------------------------------------------------------

DISPUTE_OPEN = "OPEN"
DISPUTE_EVIDENCE_GATHERED = "EVIDENCE_GATHERED"
DISPUTE_PROPOSED = "PROPOSED"
DISPUTE_APPROVED = "APPROVED"
DISPUTE_REJECTED = "REJECTED"
DISPUTE_ESCALATED = "ESCALATED"

_DISPUTE_STATUSES = (
    DISPUTE_OPEN, DISPUTE_EVIDENCE_GATHERED, DISPUTE_PROPOSED,
    DISPUTE_APPROVED, DISPUTE_REJECTED, DISPUTE_ESCALATED,
)
_DISPUTE_TERMINAL = (DISPUTE_APPROVED, DISPUTE_REJECTED, DISPUTE_ESCALATED)

DISPUTE_CLASSES = (
    "category_correction", "duplicate_charge", "unrecognized", "amount_mismatch",
)


class Dispute(Base):
    """One row per transaction dispute — the P6 workflow aggregate.

    State machine (P6_DESIGN.md §4): OPEN → EVIDENCE_GATHERED →
    PROPOSED → APPROVED/REJECTED (human-only), any non-terminal →
    ESCALATED. Transitions go through the named mark_* methods ONLY —
    the ticketing Week-2 rule in Python: a raw status write from a
    bug can't silently move a terminal dispute.

    id is UUIDv4 (URL-exposed — ChatSession enumeration argument).
    llm_calls_used is the lifetime budget counter (P4 attempts
    pattern): the loop CAS-increments it so resume-loops can't buy
    themselves a fresh budget.
    """

    __tablename__ = "disputes"

    id = Column(String, primary_key=True)
    api_key_hash = Column(
        String,
        ForeignKey("api_keys.key_hash", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    enrichment_id = Column(
        Integer,
        ForeignKey("enrichment_records.id", ondelete="SET NULL"),
        nullable=True,  # SET NULL on enrichment deletion keeps the dispute's audit row alive
    )
    claim_text = Column(String, nullable=False)
    dispute_class = Column(String, nullable=True)
    status = Column(String, nullable=False, default=DISPUTE_OPEN, index=True)
    escalation_reason = Column(String, nullable=True)
    rejection_reason = Column(String, nullable=True)
    proposal_json = Column(String, nullable=True)
    llm_calls_used = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    resolved_at = Column(DateTime, nullable=True)

    steps = relationship(
        "AgentStep",
        back_populates="dispute",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AgentStep.step_index",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('OPEN','EVIDENCE_GATHERED','PROPOSED','APPROVED','REJECTED','ESCALATED')",
            name="ck_disputes_status",
        ),
        CheckConstraint(
            "dispute_class IS NULL OR dispute_class IN "
            "('category_correction','duplicate_charge','unrecognized','amount_mismatch')",
            name="ck_disputes_class",
        ),
    )

    # --- named transitions (the ONLY way status moves) ----------------

    def _expect_not_terminal(self, action: str) -> None:
        if self.status in _DISPUTE_TERMINAL:
            raise ValueError(
                f"{action} not allowed: dispute {self.id} is already terminal ({self.status})"
            )

    def mark_evidence_gathered(self) -> None:
        if self.status != DISPUTE_OPEN:
            raise ValueError(
                f"mark_evidence_gathered requires OPEN, was {self.status} ({self.id})"
            )
        self.status = DISPUTE_EVIDENCE_GATHERED

    def mark_proposed(self, *, dispute_class: str, proposal_json: str) -> None:
        if self.status not in (DISPUTE_OPEN, DISPUTE_EVIDENCE_GATHERED):
            raise ValueError(
                f"mark_proposed requires OPEN/EVIDENCE_GATHERED, was {self.status} ({self.id})"
            )
        if dispute_class not in DISPUTE_CLASSES:
            raise ValueError(f"unknown dispute_class {dispute_class!r}")
        self.dispute_class = dispute_class
        self.proposal_json = proposal_json
        self.status = DISPUTE_PROPOSED

    def mark_approved(self) -> None:
        # Human-only route calls this; the agent loop has no path here
        # (P6_DESIGN §6 — the gate is structural).
        if self.status != DISPUTE_PROPOSED:
            raise ValueError(f"mark_approved requires PROPOSED, was {self.status} ({self.id})")
        self.status = DISPUTE_APPROVED
        self.resolved_at = datetime.now(timezone.utc)

    def mark_rejected(self, *, reason: str) -> None:
        if self.status != DISPUTE_PROPOSED:
            raise ValueError(f"mark_rejected requires PROPOSED, was {self.status} ({self.id})")
        self.rejection_reason = reason
        self.status = DISPUTE_REJECTED
        self.resolved_at = datetime.now(timezone.utc)

    def mark_escalated(self, *, reason: str) -> None:
        # Agent OR human can escalate — but never out of a terminal state.
        self._expect_not_terminal("mark_escalated")
        self.escalation_reason = reason
        self.status = DISPUTE_ESCALATED
        self.resolved_at = datetime.now(timezone.utc)


class AgentStep(Base):
    """One row per agent-loop iteration — the checkpoint + the earned
    trail (P6_DESIGN §5). Written BEFORE the action executes
    (checkpoint-then-execute): a crash between the two leaves a
    recorded intention with no effect — safe to re-run because every
    registry tool is read-only. (dispute_id, step_index) UNIQUE so a
    resumed loop that miscounts collides loudly instead of silently
    double-writing history.
    """

    __tablename__ = "agent_steps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dispute_id = Column(
        String,
        ForeignKey("disputes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_index = Column(Integer, nullable=False)
    action = Column(String, nullable=False)
    tool_name = Column(String, nullable=True)
    tool_args = Column(String, nullable=True)      # JSON
    observation = Column(String, nullable=True)    # data-framed digest (P5 rule)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    dispute = relationship("Dispute", back_populates="steps")

    __table_args__ = (
        UniqueConstraint("dispute_id", "step_index", name="uq_agent_steps_dispute_index"),
        CheckConstraint(
            "action IN ('tool_call','classify','propose','escalate')",
            name="ck_agent_steps_action",
        ),
    )


def create_dispute(
    db: Session, *, dispute_id: str, api_key_hash: str,
    enrichment_id: int | None, claim_text: str,
) -> Dispute:
    row = Dispute(
        id=dispute_id,
        api_key_hash=api_key_hash,
        enrichment_id=enrichment_id,
        claim_text=claim_text,
        status=DISPUTE_OPEN,
        llm_calls_used=0,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_dispute_owned_by(
    db: Session, *, dispute_id: str, api_key_hash: str
) -> Dispute | None:
    """None for BOTH 'no such dispute' and 'someone else's dispute' —
    the route 404s identically either way (P3 existence-hiding,
    invariant #2)."""
    return (
        db.query(Dispute)
        .filter(Dispute.id == dispute_id)
        .filter(Dispute.api_key_hash == api_key_hash)
        .one_or_none()
    )


def list_disputes_for_key(
    db: Session, *, api_key_hash: str, limit: int = 20
) -> list[Dispute]:
    return (
        db.query(Dispute)
        .filter(Dispute.api_key_hash == api_key_hash)
        .order_by(Dispute.created_at.desc())
        .limit(limit)
        .all()
    )


def append_agent_step(
    db: Session, *, dispute_id: str, step_index: int, action: str,
    tool_name: str | None = None, tool_args: str | None = None,
    observation: str | None = None,
) -> AgentStep:
    step = AgentStep(
        dispute_id=dispute_id,
        step_index=step_index,
        action=action,
        tool_name=tool_name,
        tool_args=tool_args,
        observation=observation,
    )
    db.add(step)
    db.commit()
    db.refresh(step)
    return step


def list_agent_steps(db: Session, *, dispute_id: str) -> list[AgentStep]:
    return (
        db.query(AgentStep)
        .filter(AgentStep.dispute_id == dispute_id)
        .order_by(AgentStep.step_index.asc())
        .all()
    )


def reserve_llm_call(db: Session, *, dispute_id: str, max_calls: int) -> bool:
    """CAS-increment the lifetime LLM-call budget (P4 claim pattern).
    UPDATE ... SET used = used + 1 WHERE id = ? AND used < max — one
    atomic statement, so a resumed/concurrent loop can't double-spend
    past the cap. True = call reserved; False = budget exhausted
    (caller must force-escalate, P6_DESIGN §5)."""
    updated = (
        db.query(Dispute)
        .filter(Dispute.id == dispute_id)
        .filter(Dispute.llm_calls_used < max_calls)
        .update(
            {Dispute.llm_calls_used: Dispute.llm_calls_used + 1},
            synchronize_session=False,
        )
    )
    db.commit()
    return updated == 1
