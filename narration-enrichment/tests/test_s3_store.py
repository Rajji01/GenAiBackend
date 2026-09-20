"""
Unit tests for s3_store.py using moto's in-process S3 fake.

Standing rule 3-2: no real AWS credentials, no real bucket. moto
intercepts every boto3 S3 call inside the `@mock_aws` context and
serves them from an in-memory store — the code under test is real
boto3 code, but nothing leaves the process.
"""

import importlib

import pytest
from moto import mock_aws

from narration_enrichment import config, s3_store


BUCKET = "narration-policies-test"


@pytest.fixture(autouse=True)
def _clear_settings_cache_and_client():
    # get_settings() is @lru_cache'd; without clearing it, an earlier
    # test's Settings (bucket="") would leak into the next test's
    # Settings (bucket="narration-policies-test") and vice versa.
    # Same story for s3_store._client — reset both around every test.
    config.get_settings.cache_clear()
    s3_store._reset_for_tests()
    yield
    config.get_settings.cache_clear()
    s3_store._reset_for_tests()


@pytest.fixture
def _s3_env(monkeypatch):
    # Populate env with a bucket + fake creds so boto3 stops looking
    # for real credentials on disk. moto ignores the values; it just
    # needs SOMETHING to satisfy botocore's credential resolution.
    monkeypatch.setenv("POLICY_S3_BUCKET", BUCKET)
    monkeypatch.setenv("POLICY_S3_PREFIX", "policy-docs/")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    yield


def test_is_configured_false_when_bucket_env_not_set(monkeypatch):
    monkeypatch.setenv("POLICY_S3_BUCKET", "")
    config.get_settings.cache_clear()

    assert s3_store.is_configured() is False


def test_is_configured_true_when_bucket_env_set(_s3_env):
    assert s3_store.is_configured() is True


def test_uri_for_returns_deterministic_s3_uri(_s3_env):
    # Same doc_id → same URI, so a re-ingest overwrites in place
    # rather than piling up copies. Independent of any actual upload.
    assert s3_store.uri_for("merchant_map") == f"s3://{BUCKET}/policy-docs/merchant_map.txt"


@mock_aws
def test_put_raw_doc_uploads_and_returns_uri(_s3_env):
    import boto3
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    # Reset again post-bucket-create — moto's mock is now active, so
    # the module-level lru_cache'd client needs to rebuild inside
    # the mocked context.
    s3_store._reset_for_tests()

    uri = s3_store.put_raw_doc("merchant_map", "Merchant: SWIGGY -> food_delivery.")

    assert uri == f"s3://{BUCKET}/policy-docs/merchant_map.txt"
    # Verify the object landed with the right content and metadata.
    obj = s3.get_object(Bucket=BUCKET, Key="policy-docs/merchant_map.txt")
    assert obj["Body"].read().decode("utf-8") == "Merchant: SWIGGY -> food_delivery."
    assert obj["ContentType"].startswith("text/plain")


@mock_aws
def test_get_raw_doc_round_trips_content(_s3_env):
    import boto3
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET)
    s3_store._reset_for_tests()

    original = "policy body with unicode: café ₹1000"
    s3_store.put_raw_doc("d1", original)

    fetched = s3_store.get_raw_doc("d1")
    assert fetched == original


@mock_aws
def test_put_raw_doc_overwrites_previous_object_on_same_id(_s3_env):
    # Deterministic key policy: same doc_id → same key → new put
    # replaces old body. Verifies the "no orphan versions accumulate"
    # design promise in s3_store.py's put_raw_doc docstring.
    import boto3
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    s3_store._reset_for_tests()

    s3_store.put_raw_doc("d1", "v1")
    s3_store.put_raw_doc("d1", "v2-replacement")

    body = s3.get_object(Bucket=BUCKET, Key="policy-docs/d1.txt")["Body"].read().decode("utf-8")
    assert body == "v2-replacement"


@mock_aws
def test_delete_raw_doc_removes_object(_s3_env):
    import boto3
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    s3_store._reset_for_tests()

    s3_store.put_raw_doc("d1", "to-be-deleted")
    s3_store.delete_raw_doc("d1")

    from botocore.exceptions import ClientError
    with pytest.raises(ClientError) as exc_info:
        s3.get_object(Bucket=BUCKET, Key="policy-docs/d1.txt")
    assert exc_info.value.response["Error"]["Code"] in {"NoSuchKey", "404"}


@mock_aws
def test_delete_raw_doc_on_missing_key_is_idempotent(_s3_env):
    # S3 DELETE on a nonexistent key is a 204, not an error — the
    # cleanup flow in main.py depends on this to not fail loud
    # when the DB row exists but the S3 upload never landed.
    import boto3
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET)
    s3_store._reset_for_tests()

    # Should not raise
    s3_store.delete_raw_doc("was-never-uploaded")


def test_put_raw_doc_raises_when_bucket_not_configured(monkeypatch):
    monkeypatch.setenv("POLICY_S3_BUCKET", "")
    config.get_settings.cache_clear()

    with pytest.raises(s3_store.S3NotConfiguredError):
        s3_store.put_raw_doc("d1", "hello")
