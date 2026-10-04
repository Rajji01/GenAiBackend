"""
Suite-wide bootstrap, imported by pytest before any test module.

The suite's contract (README "Test" section) is: no network, no real API
key. But config.Settings requires gemini_api_key, and db.py builds its
engine via get_settings() at import time — so on a machine without a
.env file (fresh clone, CI), collection itself died with a pydantic
ValidationError before any mock or fixture could run. On the original
dev machine a real .env masked this completely.

A placeholder key here keeps the no-key contract actually true on a
clean checkout. Nothing in the suite ever sends it anywhere: the LLM
and embedding boundaries are mocked in every test that reaches them.
setdefault (not assignment) so a developer's real environment, if
present, is left untouched.
"""

import os

os.environ.setdefault("GEMINI_API_KEY", "test-key-never-sent-anywhere")
