"""
Week 4 — a self-imposed rate limiter for the generative LLM call.

Phase 1's eval (Week 2) measured the free tier's real limits by hitting
them: 5 requests/minute AND a separate 20 requests/day cap. Phase 3's
retry-with-backoff (Week 2) handles a transient 429 gracefully, but it
still has to spend an actual failed call to discover the limit was hit -
and worse, once the *daily* cap is gone, it's gone for the rest of the
day; retrying just burns three more attempts confirming what's already
true. Rejecting locally, before the call, is strictly better: instant,
free, and the caller gets an honest "try again in N seconds" instead of
watching three retries fail one after another.

Deliberately in-process, not Redis-backed: this service runs as one
process. A distributed rate limiter would be solving a problem this
deployment doesn't have yet - see the same reasoning as RAG's "own
persisted data instead of a vector DB" decision.
"""

import threading
import time
from collections import deque
from dataclasses import dataclass


class RateLimitExceededError(Exception):
    def __init__(self, scope: str, retry_after_seconds: float):
        self.scope = scope
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"{scope} rate limit exceeded, retry after {retry_after_seconds:.1f}s")


@dataclass
class _Window:
    limit: int
    seconds: float
    calls: deque = None

    def __post_init__(self):
        self.calls = deque()

    def evict_stale(self, now: float) -> None:
        cutoff = now - self.seconds
        while self.calls and self.calls[0] <= cutoff:
            self.calls.popleft()

    def retry_after(self, now: float) -> float:
        # The oldest call in the window is the one that has to age out
        # before there's room for a new one.
        return self.seconds - (now - self.calls[0])


class RateLimiter:
    """Sliding-window limiter over two windows at once (per-minute AND
    per-day) - a request must clear both to be allowed. `time_fn` is
    injectable so tests can control time directly instead of sleeping
    for real minutes/days to prove a window resets.
    """

    def __init__(self, per_minute: int, per_day: int, time_fn=time.monotonic):
        self._time_fn = time_fn
        self._minute = _Window(limit=per_minute, seconds=60.0)
        self._day = _Window(limit=per_day, seconds=86400.0)
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Raises RateLimitExceededError if calling now would exceed
        either window; otherwise records the call and returns.
        """
        now = self._time_fn()
        with self._lock:
            self._minute.evict_stale(now)
            self._day.evict_stale(now)

            if len(self._minute.calls) >= self._minute.limit:
                raise RateLimitExceededError("per_minute", self._minute.retry_after(now))
            if len(self._day.calls) >= self._day.limit:
                raise RateLimitExceededError("per_day", self._day.retry_after(now))

            self._minute.calls.append(now)
            self._day.calls.append(now)

    def reset(self) -> None:
        # Test-only hook — production code never needs to forget history.
        with self._lock:
            self._minute.calls.clear()
            self._day.calls.clear()
