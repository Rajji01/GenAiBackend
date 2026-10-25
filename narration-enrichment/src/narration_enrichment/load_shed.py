"""
Hardening H4 — load shedding on the synchronous enrich path.

The problem (PROD_HARDENING.md §4): uvicorn's threadpool happily
accepts 100 concurrent /enrich requests even though most will spend
seconds in retrieval + provider work before being told no — and a
provider slowdown multiplies held threads exactly when the system can
do the least (metastable failure). The fix is the oldest bulkhead
there is: beyond N in-flight requests, reject in microseconds. A fast
no is kinder than a slow timeout — the caller can back off, balance
away, or queue; a held thread helps nobody.

Deliberately NOT asyncio semaphores or queueing theory (rule 3-7):
count, compare, reject. One lock, one integer.

Rejection order on this path, pinned by test (test_load_shed.py):
    1. idempotency REPLAY  — free by definition, served even at full
    2. SHED (this file)    — cheapest no: no retrieval, no quota math
    3. QUOTA (429)         — local math, after retrieval embed
    4. BREAKER (503)       — adjacent to the generative call it guards
The design paper's Q5 asks to defend the order by cost-of-saying-no;
this comment is the answer's skeleton: each gate sits exactly as late
as its signal requires and as early as its cost allows.
"""

import logging
import threading

from narration_enrichment.config import get_settings

logger = logging.getLogger(__name__)


class LoadShedError(Exception):
    """Raised when the in-flight cap is reached. The route maps it to
    503 + Retry-After: 1 — 'come back in a moment' is honest for a
    concurrency limit (unlike the breaker's cooldown, nothing is
    broken; we are just full RIGHT NOW)."""


class InFlightLimiter:
    def __init__(self, max_in_flight: int):
        self._max = max_in_flight
        self._in_flight = 0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            if self._in_flight >= self._max:
                logger.warning("load_shed in_flight=%d max=%d", self._in_flight, self._max)
                raise LoadShedError()
            self._in_flight += 1

    def release(self) -> None:
        with self._lock:
            # Guarded so a buggy double-release can never drive the
            # counter negative and silently raise the effective cap.
            if self._in_flight > 0:
                self._in_flight -= 1

    @property
    def in_flight(self) -> int:
        with self._lock:
            return self._in_flight


_settings = get_settings()
enrich_shed = InFlightLimiter(max_in_flight=_settings.enrich_max_in_flight)


def _reset_for_tests() -> None:
    enrich_shed._in_flight = 0
