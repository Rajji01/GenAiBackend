"""
Hardening H2 — a circuit breaker on the generative-provider boundary.

The problem (PROD_HARDENING.md §2): during a SUSTAINED provider
outage, every request burns the full 20s timeout, holds a threadpool
worker, runs tenacity's bounded retries into a dead upstream, and
fails anyway. tenacity answers "this CALL failed, try again"; nothing
answers "this PROVIDER is down, stop asking." That second answer is
this file — Hystrix's state machine, smallest honest version:

    CLOSED ──(N consecutive counted failures)──► OPEN
    OPEN   ──(cooldown elapsed)──► HALF_OPEN (exactly one probe)
    HALF_OPEN ── probe success ──► CLOSED (counters reset)
    HALF_OPEN ── probe failure ──► OPEN (fresh cooldown)

Deliberate choices, each flagged in the design paper:
- Pure Python, no new dependency (rule 3-7).
- WHAT counts as a failure is the CALLER's decision (service.py's
  transient/timeout whitelist) — the breaker just counts. Tripping on
  non-transients (a 422, a validation error) would turn one weird
  request into a self-inflicted outage.
- Consecutive-failures threshold, not a rolling error-rate window:
  the right trade at this traffic; the paper names the load level
  that would flip it.
- HALF_OPEN admits exactly ONE in-flight probe; everyone else fails
  fast. The recovery test costs one request, not a herd.
- Injectable clock (`time_fn`) — the same testability pattern as
  rate_limiter.py and the queue fakes. Staleness math never sleeps
  in a test.
"""

import logging
import threading
import time

from narration_enrichment.config import get_settings

logger = logging.getLogger(__name__)

CLOSED = "CLOSED"
OPEN = "OPEN"
HALF_OPEN = "HALF_OPEN"


class CircuitOpenError(Exception):
    """Raised by allow() in microseconds while the circuit is OPEN
    (or while HALF_OPEN's single probe slot is taken). Carries how
    long the caller should wait — the route maps this straight to
    503 + Retry-After without touching the provider."""

    def __init__(self, retry_after_seconds: float):
        self.retry_after_seconds = max(0.0, retry_after_seconds)
        super().__init__(
            f"circuit open; retry after {self.retry_after_seconds:.0f}s"
        )


class CircuitBreaker:
    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        cooldown_seconds: float = 30.0,
        time_fn=time.monotonic,
    ):
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._time_fn = time_fn
        self._lock = threading.Lock()
        self._state = CLOSED
        self._consecutive_failures = 0
        self._opened_at = 0.0
        self._probe_in_flight = False

    @property
    def state(self) -> str:
        with self._lock:
            return self._effective_state()

    def _effective_state(self) -> str:
        # Called under the lock. OPEN lazily becomes HALF_OPEN once
        # the cooldown has elapsed — no background timer thread; the
        # next caller's allow() performs the transition, same way the
        # rate limiter evicts stale entries on access.
        if self._state == OPEN and (
            self._time_fn() - self._opened_at >= self._cooldown_seconds
        ):
            self._state = HALF_OPEN
            self._probe_in_flight = False
            logger.info("circuit_half_open")
        return self._state

    def allow(self) -> None:
        """Gate a call. Returns instantly when CLOSED; grants the one
        probe slot when HALF_OPEN; raises CircuitOpenError otherwise.
        The whole point is that the failure path here costs
        microseconds — a fast no, exactly when the system is busiest."""
        with self._lock:
            state = self._effective_state()
            if state == CLOSED:
                return
            if state == HALF_OPEN and not self._probe_in_flight:
                self._probe_in_flight = True
                logger.info("circuit_probe_granted")
                return
            remaining = self._cooldown_seconds - (self._time_fn() - self._opened_at)
            if state == HALF_OPEN:
                # Probe slot taken: tell the caller to come back soon,
                # not after a whole fresh cooldown — the probe's result
                # is seconds away either way.
                remaining = 1.0
            raise CircuitOpenError(remaining)

    def record_success(self) -> None:
        """The provider ANSWERED. Note that an unhappy answer (a 4xx,
        a validation failure) still proves the provider is alive —
        the caller records success for those too; only the
        transient/timeout whitelist records failure."""
        with self._lock:
            if self._state in (HALF_OPEN, OPEN):
                # OPEN is possible here only for a straggler whose
                # call started before the circuit opened; treat it as
                # the same good news a probe success is.
                logger.info("circuit_closed_after_recovery")
            self._state = CLOSED
            self._consecutive_failures = 0
            self._probe_in_flight = False

    def record_failure(self) -> None:
        with self._lock:
            state = self._effective_state()
            if state == HALF_OPEN:
                # The probe failed: back to OPEN with a FRESH cooldown.
                self._state = OPEN
                self._opened_at = self._time_fn()
                self._probe_in_flight = False
                logger.warning("circuit_reopened_probe_failed")
                return
            self._consecutive_failures += 1
            if self._state == CLOSED and self._consecutive_failures >= self._failure_threshold:
                self._state = OPEN
                self._opened_at = self._time_fn()
                logger.warning(
                    "circuit_opened consecutive_failures=%d", self._consecutive_failures
                )


# --- the process-wide breaker around the generative boundary ----------------
#
# ONE breaker shared by /enrich and /chat on purpose: they call the
# same upstream, so their fate is shared — pretending otherwise with
# per-route breakers would just mean each route independently burns
# its own threshold against the same dead provider.

_settings = get_settings()
llm_breaker = CircuitBreaker(
    failure_threshold=_settings.breaker_failure_threshold,
    cooldown_seconds=_settings.breaker_cooldown_seconds,
)


def _reset_for_tests() -> None:
    llm_breaker._state = CLOSED
    llm_breaker._consecutive_failures = 0
    llm_breaker._probe_in_flight = False
    llm_breaker._opened_at = 0.0
