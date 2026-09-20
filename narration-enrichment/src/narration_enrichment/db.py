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
