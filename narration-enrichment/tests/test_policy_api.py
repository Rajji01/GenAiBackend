"""
Integration tests for the P2 policy routes:
  POST   /policies/ingest
  GET    /policies
  DELETE /policies/{doc_id}

Same test harness as tests/test_api.py: real FastAPI app through
TestClient, in-memory SQLite via StaticPool, embedding call mocked
at the rag module boundary (same seam main.py binds through).
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from google.genai.errors import APIError
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from narration_enrichment.db import Base, PolicyChunk, PolicyDoc, get_db
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


# NOTE: intentionally NOT assigning app.dependency_overrides[get_db]
# at module scope — tests/test_api.py already sets its own override
# there, and whichever module imports last would silently clobber
# the other's engine, causing the "wrong" test module to hit an
# engine with no seed data. Instead each test in THIS file installs
# the override as a fixture and restores whatever was there before.
client = TestClient(app)


FAKE_EMBEDDING = [0.1] * 256


@pytest.fixture(autouse=True)
def _policy_db_override():
    # Function-scoped so a test in this file always runs against
    # this module's engine, regardless of import order relative to
    # tests/test_api.py. On teardown, restore the previous override
    # so any other module that runs after this one keeps working.
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
def _clean_policy_tables():
    # Order matters — chunks first (FK dependency). Empty every test.
    with _test_engine.begin() as conn:
        conn.execute(Base.metadata.tables["policy_chunks"].delete())
        conn.execute(Base.metadata.tables["policy_docs"].delete())
    yield


@pytest.fixture(autouse=True)
def _mock_embed():
    # Same boundary as tests/test_api.py — main.py's policies_ingest
    # binds `rag.embed_text(raw_client, text, task_type=...)`; patch
    # rag.embed_text so no real embedding call happens.
    with patch("narration_enrichment.rag.embed_text", return_value=FAKE_EMBEDDING):
        yield


def _ingest(doc_id: str = "d1", title: str = "t", content: str = "hello world"):
    return client.post(
        "/policies/ingest",
        json={"doc_id": doc_id, "title": title, "content": content},
    )


def test_ingest_creates_doc_and_returns_summary():
    r = _ingest(doc_id="merchant_map", title="Merchant Map", content="A" * 1200)

    assert r.status_code == 200
    body = r.json()
    assert body["doc_id"] == "merchant_map"
    assert body["unchanged"] is False
    assert body["chunks_ingested"] == 3     # 1200 chars → 3 chunks at defaults
    assert len(body["checksum"]) == 64      # sha256 hex


def test_ingest_same_content_returns_unchanged_true():
    _ingest(content="stable body")
    r = _ingest(content="stable body")

    assert r.status_code == 200
    assert r.json()["unchanged"] is True


def test_ingest_rejects_empty_content_as_422():
    # Pydantic-level rejection on min_length=1 — never reaches the
    # service, no DB row, no embed call. This is 422 (Pydantic), not
    # 400 (service-level ValueError from a whitespace-only body).
    r = client.post("/policies/ingest", json={"doc_id": "d1", "title": "t", "content": ""})
    assert r.status_code == 422


def test_ingest_rejects_whitespace_only_content_as_400():
    # Passes the Pydantic min_length=1 check (a single space is 1 char)
    # but the service layer rejects it via chunker.chunk() returning
    # [] — which the service maps to a ValueError → 400.
    r = client.post("/policies/ingest", json={"doc_id": "d1", "title": "t", "content": "   \n  "})
    assert r.status_code == 400


def test_ingest_maps_provider_apierror_to_503():
    # Simulate an embedding-provider outage during ingest — the ingest
    # aborts (no partial state), the route maps APIError to 503 with
    # the same shape /enrich uses for the same failure class.
    with patch("narration_enrichment.rag.embed_text",
               side_effect=APIError(code=503, response_json={}, response=None)):
        r = _ingest()

    assert r.status_code == 503
    # Nothing persisted — the abort-on-any-embed-failure contract holds
    # end-to-end, not just in the unit test.
    with _test_engine.connect() as conn:
        assert conn.execute(
            Base.metadata.tables["policy_docs"].select()
        ).fetchall() == []


def test_list_policies_returns_docs_with_chunk_counts_newest_first():
    _ingest(doc_id="old", title="old-t", content="A" * 600)  # 2 chunks
    _ingest(doc_id="new", title="new-t", content="B" * 200)  # 1 chunk

    r = client.get("/policies")

    assert r.status_code == 200
    docs = r.json()
    assert [d["doc_id"] for d in docs] == ["new", "old"]
    assert [d["chunk_count"] for d in docs] == [1, 2]


def test_list_policies_on_empty_corpus_returns_empty_list():
    r = client.get("/policies")

    assert r.status_code == 200
    assert r.json() == []


def test_delete_policy_removes_doc_and_chunks_and_returns_204():
    _ingest(doc_id="d1", title="t", content="A" * 600)
    # Sanity: rows exist
    with _test_engine.connect() as conn:
        assert conn.execute(Base.metadata.tables["policy_docs"].select()).fetchall()

    r = client.delete("/policies/d1")

    assert r.status_code == 204
    with _test_engine.connect() as conn:
        assert conn.execute(Base.metadata.tables["policy_docs"].select()).fetchall() == []
        assert conn.execute(Base.metadata.tables["policy_chunks"].select()).fetchall() == []


def test_delete_missing_policy_is_idempotent_204():
    r = client.delete("/policies/does-not-exist")

    assert r.status_code == 204
