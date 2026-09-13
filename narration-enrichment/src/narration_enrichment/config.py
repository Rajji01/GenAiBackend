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
    request_timeout_seconds: float = 10.0
    max_retries: int = 3


@lru_cache
def get_settings() -> Settings:
    # Cached so Settings() — which reads the environment and .env file —
    # only runs once per process, not once per request.
    return Settings()
