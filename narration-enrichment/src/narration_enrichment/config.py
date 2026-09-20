"""
All environment-dependent knobs live here, in one place, read once at
startup. Nothing in the rest of the codebase should read os.environ
directly or hardcode a model name — that's exactly the "config commented
out, nobody knows what's actually running" problem from the Java project,
just in a new language.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    gemini_api_key: str
    model_name: str = "gemini-3.6-flash"

    # Both of these are real production knobs, not decoration: a slow LLM
    # provider must not be allowed to hang a request forever, and a
    # malformed/unparseable output must fail after a bounded number of
    # attempts rather than retrying forever.
    #
    # 10.0 was the original guess and was too tight: a Week 2 eval run
    # against gemini-3.6-flash (a reasoning model, see Day 1's thinking-
    # token finding) measured a 33% timeout rate at 10s under real network
    # conditions. Raised to 20.0 based on that measurement, not a guess.
    request_timeout_seconds: float = 20.0
    max_retries: int = 3

    # SQLite by default — one file, zero setup, plenty for this project's
    # scale. A real multi-writer production deployment would reach for
    # Postgres here, but the repository pattern below doesn't change.
    database_url: str = "sqlite:///./narration_enrichment.db"

    # Week 4 — the exact free-tier limits Phase 1's eval measured live,
    # not a guess. Kept overridable via env for the day these numbers
    # change (a paid tier, a quota increase) without a code change.
    enrich_rate_limit_per_minute: int = 5
    enrich_rate_limit_per_day: int = 20

    # P2 Day 4 — S3 backing for raw policy docs. Empty string = S3
    # disabled (dev default); source_uri on new PolicyDoc rows will
    # be None. Any non-empty string turns on the S3 code path in
    # main.py's /policies/ingest and s3_store.py. Real bucket +
    # credentials are Rajat's per standing rule 3-2; this codebase
    # only wires boto3, never creates AWS resources.
    policy_s3_bucket: str = ""
    policy_s3_prefix: str = "policy-docs/"
    aws_region: str = "ap-south-1"


@lru_cache
def get_settings() -> Settings:
    # Cached so Settings() — which reads the environment and .env file —
    # only runs once per process, not once per request.
    return Settings()
