"""
Unit tests for rate_limiter.py — pure logic, no network, no real waiting.
A fake clock (a plain float the test controls) is injected as `time_fn`
so a "does the window reset after 60s" test takes milliseconds, not a
minute.
"""

import pytest

from narration_enrichment.rate_limiter import RateLimitExceededError, RateLimiter


class FakeClock:
    def __init__(self, start: float = 0.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_allows_calls_up_to_the_per_minute_limit():
    clock = FakeClock()
    limiter = RateLimiter(per_minute=3, per_day=100, time_fn=clock)

    limiter.acquire()
    limiter.acquire()
    limiter.acquire()  # the 3rd call, still within limit=3


def test_rejects_the_call_that_would_exceed_the_per_minute_limit():
    clock = FakeClock()
    limiter = RateLimiter(per_minute=2, per_day=100, time_fn=clock)

    limiter.acquire()
    limiter.acquire()

    with pytest.raises(RateLimitExceededError) as exc_info:
        limiter.acquire()
    assert exc_info.value.scope == "per_minute"


def test_per_minute_window_resets_once_the_oldest_call_ages_out():
    clock = FakeClock()
    limiter = RateLimiter(per_minute=1, per_day=100, time_fn=clock)

    limiter.acquire()
    with pytest.raises(RateLimitExceededError):
        limiter.acquire()

    clock.advance(60.1)  # the first call is now outside the 60s window
    limiter.acquire()  # should succeed — no exception


def test_per_day_limit_is_enforced_independently_of_per_minute():
    clock = FakeClock()
    # per_minute is generous so only the per_day cap can trip here.
    limiter = RateLimiter(per_minute=100, per_day=2, time_fn=clock)

    limiter.acquire()
    clock.advance(70)  # clears the per-minute window between calls
    limiter.acquire()
    clock.advance(70)

    with pytest.raises(RateLimitExceededError) as exc_info:
        limiter.acquire()
    assert exc_info.value.scope == "per_day"


def test_retry_after_seconds_reflects_how_long_until_the_oldest_call_expires():
    clock = FakeClock()
    limiter = RateLimiter(per_minute=1, per_day=100, time_fn=clock)

    limiter.acquire()
    clock.advance(10)  # 10s into the 60s window

    with pytest.raises(RateLimitExceededError) as exc_info:
        limiter.acquire()
    assert exc_info.value.retry_after_seconds == pytest.approx(50.0, abs=0.01)


def test_reset_clears_all_recorded_calls():
    clock = FakeClock()
    limiter = RateLimiter(per_minute=1, per_day=100, time_fn=clock)

    limiter.acquire()
    limiter.reset()

    limiter.acquire()  # would have raised if reset() hadn't cleared state
