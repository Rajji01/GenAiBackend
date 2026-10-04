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

    # P4 Day 2 — async ingestion. Empty queue URL = in-memory queue
    # (dev/test default, zero AWS needed) — same gating pattern as
    # policy_s3_bucket above. A real SQS URL flips the backend on
    # Day 4; the URL itself comes from Rajat's Terraform (rule 3-2).
    ingest_queue_url: str = ""
    # Intake valve (P4_DESIGN.md §8): above this many QUEUED+PROCESSING
    # jobs the API refuses new async ingests with 429 + Retry-After
    # rather than promising work it can't run for hours. Generous
    # default — at ~8 min per 40-chunk doc on the free tier, 100 jobs
    # is already half a day of worker time.
    ingest_max_backlog: int = 100
    # P4 Day 3 — job-level retry budget. attempts counts CLAIMS (the
    # CAS increments it), so 3 means: first run + two retries, then
    # DEAD. Separate knob from the call-level tenacity retry inside
    # a single attempt — see P4_DESIGN.md §7 for why the two must
    # not be conflated.
    ingest_max_attempts: int = 3
    # How long the worker sleeps between polls when the queue came
    # back empty. Irrelevant under load (a non-empty receive loops
    # immediately); only sets idle-queue latency.
    worker_poll_interval_seconds: float = 2.0


@lru_cache
def get_settings() -> Settings:
    # Cached so Settings() — which reads the environment and .env file —
    # only runs once per process, not once per request.
    return Settings()
