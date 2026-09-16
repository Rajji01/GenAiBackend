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

from sqlalchemy import Column, DateTime, Float, Integer, String, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

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
