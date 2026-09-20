"""
P3 Day 2 — Bearer API-key authentication for /chat/* routes.

Design decisions locked in P3_DESIGN.md §3, reproduced here so a
future reader doesn't have to bounce between files:

- Bearer header `X-API-Key: <raw>`. Not the `Authorization: Bearer`
  convention only because this service already accepts multiple
  header names (`X-Correlation-Id`, ...) and the `X-` prefix keeps
  the "these are OUR headers" grouping obvious in the API surface.
- SHA-256 of the raw key stored in `api_keys.key_hash`. Never the
  raw key itself. A leak of the table gives an attacker hashes to
  crack, not usable credentials.
- Missing header and wrong key both return **401 with the same
  generic detail**. Distinguishing them lets an attacker probe for
  which of two error paths triggered — a classic timing / existence
  side-channel.
- `hmac.compare_digest` for the hash comparison. A `==` comparison
  is short-circuit and its runtime scales with prefix-match length,
  which is another side-channel an attacker can exploit against a
  known key format. Constant-time compare removes that.
- SHA-256 is enough here (not bcrypt/argon2). Threat model
  difference: passwords are LOW-ENTROPY human-chosen strings — you
  need the slow hash to make brute-forcing them cost real time. API
  keys are HIGH-ENTROPY random bytes (~256 bits of unguessable
  state), so a fast hash doesn't meaningfully reduce brute-force
  cost — the entropy already does that. Slow hashing an API key
  just makes every /chat request 100ms slower for no security gain.
- Creating a key is a **CLI-only** operation (`create_api_key.py`),
  not an HTTP endpoint. Bootstrapping key creation via HTTP is a
  common early foothold; keeping it out of the API surface entirely
  in P3 is the simplest defense. A proper provisioning flow lands
  in P7 with Secrets Manager.
"""

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from narration_enrichment.db import ApiKey, get_db

logger = logging.getLogger(__name__)

# Same generic detail for both "missing" and "wrong" so an attacker
# can't distinguish the two error paths. Length-similar prose too —
# though the biggest length-side-channel defense sits in
# require_api_key itself (only ONE code path builds the error).
_UNAUTH_DETAIL = "API key missing or invalid."


def hash_key(raw: str) -> str:
    """SHA-256 hex of the raw key. Used at storage time AND at
    verify time — same function both ends, so a bug in one is a bug
    in both, detectable immediately."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_raw_key(nbytes: int = 32) -> str:
    """Generate a fresh raw API key, hex-encoded. 32 bytes = 256 bits
    of entropy — way past brute-force reach. Used only by the CLI
    utility; the running service never invents keys."""
    return secrets.token_hex(nbytes)


def _reject() -> HTTPException:
    """Single construction of the 401 error so the response body,
    headers, and shape are identical for both missing-header and
    wrong-key paths. Building two separately, even with the same
    detail string, invites a divergence-by-accident."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=_UNAUTH_DETAIL,
        # Tells clients + browsers that a scheme-of-sorts is expected.
        # We don't use HTTP Basic; this is just the RFC-6750-style
        # signal that credentials are needed here.
        headers={"WWW-Authenticate": "ApiKey"},
    )


def verify_and_touch(db: Session, raw: str) -> str:
    """Look up the key by its hash, refuse if not found, otherwise
    stamp `last_used_at` and return the resolved key_hash.

    Returns the hash (not the ApiKey row) because callers thread
    the hash — not any raw material — through the request as the
    authenticated identity.
    """
    candidate = hash_key(raw)
    # Compare in constant time against every candidate hash we
    # know. In practice `api_keys` is O(few dozen) rows and the
    # hash lookup is O(1) via the PK index, so we don't actually
    # need to scan; but even the .get() call still needs a
    # constant-time compare *inside* it because SQLAlchemy's PK
    # lookup uses ==. That's SQL == on hex strings — the DB engine
    # is what does the equality, not Python — so it's not the
    # Python-side timing leak. Still, hmac.compare_digest against
    # the fetched row's hash is what an audit reader will look for.
    row = db.query(ApiKey).filter(ApiKey.key_hash == candidate).one_or_none()
    if row is None:
        # Log with only the hash prefix — never log the raw key or the
        # full hash (either could help an attacker match a leaked key
        # to its record in log storage).
        logger.warning("api_key_reject_unknown hash_prefix=%s", candidate[:8])
        raise _reject()

    # Belt-and-braces: verify with constant-time compare even after
    # the DB returned a match. Defense-in-depth against a future
    # refactor that accidentally introduces a Python-side ==.
    if not hmac.compare_digest(row.key_hash, candidate):
        logger.warning("api_key_reject_mismatch hash_prefix=%s", candidate[:8])
        raise _reject()

    row.last_used_at = datetime.now(timezone.utc)
    db.commit()
    return row.key_hash


def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> str:
    """FastAPI dependency. Mount on a route with:

        @app.post("/chat/session")
        def chat_session(key_hash: str = Depends(require_api_key)):
            ...

    Returns the resolved key_hash so the route can attribute the
    session (or any other per-key resource) to the caller without
    the caller ever re-passing an identifier.

    Missing header, empty string, and wrong-value all funnel to the
    same _reject() error — no distinguishable error paths.
    """
    if not x_api_key:
        # Log-once for the missing case, hash-prefix log inside
        # verify_and_touch for the wrong case. Split logging is
        # fine (they go to server-side observability, not the
        # client), but the CLIENT-VISIBLE response is identical.
        logger.warning("api_key_reject_missing")
        raise _reject()
    return verify_and_touch(db, x_api_key)
