"""
P3 Day 2 tests — API key auth.

Unit tests hit auth.hash_key + auth.verify_and_touch directly against
real in-memory SQLite (the SQL == on hash strings + the timestamp
touch are what's being tested; mocking them away would test the
mock).

Integration tests mount a stub route with Depends(require_api_key)
on the same app + TestClient the other integration tests use, and
prove the 401 (missing) / 401 (wrong) / 200 (valid) paths — plus
that 401 responses look byte-for-byte identical whether the key was
missing or wrong (§3 existence-hiding rule from P3_DESIGN).
"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from narration_enrichment import auth
from narration_enrichment.db import ApiKey, Base, get_db, insert_api_key


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


# ---------------------------------------------------------------------------
# Unit — hash + verify + generate
# ---------------------------------------------------------------------------


def test_hash_key_is_deterministic():
    a = auth.hash_key("hello")
    b = auth.hash_key("hello")
    c = auth.hash_key("hello ")   # single trailing space
    assert a == b
    assert a != c
    assert len(a) == 64            # sha256 hex


def test_generate_raw_key_is_high_entropy_and_unique():
    keys = {auth.generate_raw_key() for _ in range(50)}
    assert len(keys) == 50         # 50/50 unique — collision-free at this size
    for k in keys:
        assert len(k) == 64        # 32 bytes hex = 64 chars
        assert all(c in "0123456789abcdef" for c in k)


def test_verify_and_touch_stamps_last_used(db_session):
    raw = auth.generate_raw_key()
    insert_api_key(db_session, key_hash=auth.hash_key(raw), label="test")

    before = db_session.query(ApiKey).one().last_used_at
    assert before is None          # never touched before

    resolved = auth.verify_and_touch(db_session, raw)

    assert resolved == auth.hash_key(raw)
    after = db_session.query(ApiKey).one().last_used_at
    assert after is not None       # stamped on successful verify


def test_verify_and_touch_rejects_unknown_key(db_session):
    from fastapi import HTTPException
    # No row inserted — every candidate is unknown.
    with pytest.raises(HTTPException) as exc_info:
        auth.verify_and_touch(db_session, "not-a-real-key")
    assert exc_info.value.status_code == 401


def test_verify_and_touch_does_not_leak_details_in_the_error(db_session):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        auth.verify_and_touch(db_session, "wrongkey")
    # The detail is generic — same body for missing vs wrong so an
    # attacker can't distinguish them. If a future change makes the
    # detail more informative, this test catches it and the security
    # note in auth.py's docstring stops being true.
    assert exc_info.value.detail == "API key missing or invalid."


# ---------------------------------------------------------------------------
# Integration — require_api_key on a mounted route
# ---------------------------------------------------------------------------

# Build a minimal FastAPI app JUST for these tests — mounting on the
# real narration_enrichment.main.app would pollute it with a test-only
# route. The app is intentionally tiny so nothing in it can drift out
# of sync with production behavior.
_app = FastAPI()


@_app.get("/protected")
def _protected(key_hash: str = Depends(auth.require_api_key)) -> dict:
    return {"key_hash_prefix": key_hash[:8]}


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


_app.dependency_overrides[get_db] = _override_get_db
_client = TestClient(_app)


@pytest.fixture(autouse=True)
def _clean_api_keys():
    with _test_engine.begin() as conn:
        conn.execute(Base.metadata.tables["api_keys"].delete())
    yield


def _seed_key(label: str = "test") -> str:
    raw = auth.generate_raw_key()
    db = _TestSessionLocal()
    insert_api_key(db, key_hash=auth.hash_key(raw), label=label)
    db.close()
    return raw


def test_missing_header_returns_401_with_generic_detail():
    r = _client.get("/protected")

    assert r.status_code == 401
    assert r.json() == {"detail": "API key missing or invalid."}
    assert r.headers.get("www-authenticate") == "ApiKey"


def test_wrong_key_returns_401_with_generic_detail_identical_to_missing():
    _seed_key()

    r = _client.get("/protected", headers={"X-API-Key": "not-a-real-key"})

    assert r.status_code == 401
    # Byte-for-byte identical body + relevant headers to the missing-
    # header case above — that's the existence-hiding contract.
    assert r.json() == {"detail": "API key missing or invalid."}
    assert r.headers.get("www-authenticate") == "ApiKey"


def test_empty_header_value_is_treated_as_missing():
    r = _client.get("/protected", headers={"X-API-Key": ""})

    assert r.status_code == 401
    assert r.json() == {"detail": "API key missing or invalid."}


def test_valid_key_returns_200_and_the_resolved_key_hash():
    raw = _seed_key()

    r = _client.get("/protected", headers={"X-API-Key": raw})

    assert r.status_code == 200
    assert r.json() == {"key_hash_prefix": auth.hash_key(raw)[:8]}


def test_last_used_at_is_stamped_on_a_successful_call():
    raw = _seed_key()

    _client.get("/protected", headers={"X-API-Key": raw})

    db = _TestSessionLocal()
    row = db.query(ApiKey).one()
    assert row.last_used_at is not None
    db.close()


def test_insert_api_key_repo_function_roundtrips():
    """The CLI utility calls insert_api_key + we verify it can be
    looked up via the same auth.verify_and_touch path — proves the
    two seams (CLI create + route verify) genuinely agree on
    key_hash format."""
    db = _TestSessionLocal()
    raw = auth.generate_raw_key()
    insert_api_key(db, key_hash=auth.hash_key(raw), label="cli-created")

    resolved = auth.verify_and_touch(db, raw)

    assert resolved == auth.hash_key(raw)
    db.close()
