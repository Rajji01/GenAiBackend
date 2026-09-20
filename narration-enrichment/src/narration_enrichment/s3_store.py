"""
P2 Day 4 — S3 wrapper for raw policy documents.

The narration track's first AWS touchpoint (per Jarvis_GenAI_Path.md's
"P4 is where AWS really lives, but P2 gets S3 for docs"). This module
is intentionally small: two functions (put + get) around one boto3
S3 client, plus a "not configured" fallback so dev without AWS still
works.

Design (P2_DESIGN.md sec 4): raw docs go to S3 (durable source of
truth), chunks + embeddings stay in SQLite (fast retrieval, no S3
round-trip per /enrich). Losing SQLite is annoying (rebuild by
re-running ingest against each S3 doc); losing S3 is real data loss.
This is what the storage split earns.

Standing rule 3-2 (reconfirmed 2026-09-20): real AWS bucket +
credentials are Rajat's job. This module only:
  - lazily builds a boto3.client('s3') when a bucket is configured
  - uploads / fetches / deletes objects under a prefix
  - is fully exercisable via moto in tests without AWS credentials
"""

import logging
from functools import lru_cache
from typing import Any

from narration_enrichment.config import get_settings

logger = logging.getLogger(__name__)


class S3NotConfiguredError(RuntimeError):
    """Raised by call sites that require S3 when the bucket isn't set.

    The policies_ingest route treats S3 as optional (source_uri
    becomes None if this is raised in dev), but future call sites
    that MUST have durable storage can catch this and fail loudly.
    """


@lru_cache
def _client():
    """Lazy-built boto3 S3 client, cached at module scope.

    Not eager because pytest sessions that never touch S3 shouldn't
    pay for the client construction, and dev environments without
    AWS credentials shouldn't fail on import. Wrapped in a function
    so tests can `s3_store._client.cache_clear()` between tests that
    swap credentials or region.
    """
    import boto3
    settings = get_settings()
    return boto3.client("s3", region_name=settings.aws_region)


def _bucket() -> str:
    settings = get_settings()
    if not settings.policy_s3_bucket:
        raise S3NotConfiguredError(
            "POLICY_S3_BUCKET is not set — S3 backing is disabled. "
            "Set it in .env to enable durable raw-doc storage."
        )
    return settings.policy_s3_bucket


def _key(doc_id: str) -> str:
    """S3 object key for a doc's raw text. Deterministic — same
    doc_id always maps to the same key, so a re-ingest overwrites
    the previous object rather than piling up copies."""
    prefix = get_settings().policy_s3_prefix
    return f"{prefix}{doc_id}.txt"


def put_raw_doc(doc_id: str, content: str) -> str:
    """Upload the raw doc bytes to S3 and return the s3:// URI.

    The URI goes into PolicyDoc.source_uri so a future backfill
    ("re-embed every doc from its S3 source") can find the original
    text without depending on whatever the caller passed at ingest
    time. Overwrites on same doc_id — S3 keys are deterministic
    (see _key). Uses UTF-8 (documented in ContentType) so a get_raw_doc
    that decodes with anything else fails loudly instead of silently
    mangling bytes.
    """
    bucket = _bucket()
    key = _key(doc_id)
    _client().put_object(
        Bucket=bucket,
        Key=key,
        Body=content.encode("utf-8"),
        ContentType="text/plain; charset=utf-8",
    )
    uri = f"s3://{bucket}/{key}"
    logger.info("policy_doc_uploaded doc_id=%s uri=%s bytes=%d", doc_id, uri, len(content))
    return uri


def get_raw_doc(doc_id: str) -> str:
    """Fetch the raw doc back from S3.

    Used by the "rebuild chunks from S3" backfill flow — not on the
    /enrich hot path. Decoded as UTF-8 to match put_raw_doc's
    encoding; any decoding error surfaces as UnicodeDecodeError so
    the caller knows the bytes in S3 aren't what this module wrote.
    """
    response = _client().get_object(Bucket=_bucket(), Key=_key(doc_id))
    return response["Body"].read().decode("utf-8")


def delete_raw_doc(doc_id: str) -> None:
    """Idempotent — S3 DELETE on a missing key returns 204 anyway.
    Called from the DELETE /policies/{doc_id} route so removing a
    doc from the corpus removes it from S3 too (no orphan objects).
    """
    _client().delete_object(Bucket=_bucket(), Key=_key(doc_id))


def is_configured() -> bool:
    """True iff a bucket is set — cheap read for the route to decide
    'upload to S3' vs 'skip and record source_uri=None'."""
    return bool(get_settings().policy_s3_bucket)


def uri_for(doc_id: str) -> str:
    """Same URI put_raw_doc would return, without doing any I/O.
    Handy for tests + for the ingest orchestrator to record a URI
    even if the upload happens elsewhere."""
    return f"s3://{_bucket()}/{_key(doc_id)}"


def _reset_for_tests() -> None:
    """Test hook — clears the client cache so tests can swap in a
    moto-mocked boto3 environment cleanly. Not called anywhere in
    production code paths."""
    _client.cache_clear()
