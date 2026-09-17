"""
Week 4 — a correlation ID for every request, the Python equivalent of the
ticketing-platform track's CorrelationIdFilter (same idea, different
language's tools). One process now handles requests that fan out into
several internal calls each — RAG retrieval, the rate limiter, the
generative call, a DB write — and every log line from all of them needs
to be traceable back to the one request that caused them.

Python's logging module has no built-in per-request context the way
Java's MDC does, but `contextvars.ContextVar` gives the same guarantee
for async code: a value set inside one request's coroutine is visible to
every `await` inside that same request, and invisible to concurrently
running requests — exactly the isolation MDC provides via thread-locals
in a threaded server.
"""

import logging
import uuid
from contextvars import ContextVar

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="none")

HEADER_NAME = "X-Correlation-Id"


def new_correlation_id() -> str:
    return str(uuid.uuid4())


def set_correlation_id(value: str) -> None:
    _correlation_id.set(value)


def get_correlation_id() -> str:
    return _correlation_id.get()


class CorrelationIdLogFilter(logging.Filter):
    """Attaches the current request's correlation id to every LogRecord,
    so a single %(correlation_id)s in the log format shows it on every
    line — without every logger.info() call passing it explicitly.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id()
        return True
