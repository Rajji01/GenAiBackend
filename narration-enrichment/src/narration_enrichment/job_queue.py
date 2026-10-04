"""
P4 Day 2 — the queue boundary between the API process and the Worker
process.

The message carries ONLY a job_id. The `ingest_jobs` row is the source
of truth for everything else (content, status, attempts); the message
is a delivery hint that says "go look at this row" (P4_DESIGN.md §3/§5).
That keeps messages tiny (SQS caps a message at 256KB — a policy doc
wouldn't reliably fit), and it means a lost/duplicated message never
loses or duplicates *state*, only a wake-up call.

Two implementations will live behind the same four-method interface:

- `InMemoryJobQueue` (this file, Day 2) — a deque with
  visibility-timeout semantics faked well enough for tests and
  single-machine dev. Default whenever `INGEST_QUEUE_URL` is empty,
  exactly like `POLICY_S3_BUCKET` gates the S3 path (P2 Day 4): the
  AWS code path exists, is off by default, and dev needs zero AWS.
- `SqsJobQueue` (Day 4) — boto3 against a real/moto SQS queue.
  Visibility timeout and maxReceiveCount/DLQ become queue-level
  config owned by Rajat's Terraform (standing rule 3-2).

Why an interface at all, given rule 3-7 (don't overengineer): there
are genuinely two implementations from day one — tests + dev need
in-memory, the deploy target is SQS — and the interface is four
methods. Second concrete case justifies the abstraction.

The clock is injected (`time_fn`, same pattern as rate_limiter.py)
so the visibility-timeout test can prove re-delivery without a real
30-second sleep.
"""

import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Protocol

from narration_enrichment.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QueueMessage:
    """One received message. `receipt` identifies THIS delivery (not
    the job): deleting acks the delivery, and a message re-delivered
    after a visibility timeout carries a fresh receipt — mirroring
    SQS's ReceiptHandle semantics so the worker code written against
    the in-memory queue is already correct against the real one."""

    job_id: str
    receipt: str


class JobQueue(Protocol):
    def send(self, job_id: str) -> None: ...

    def receive(self, max_messages: int = 1) -> list[QueueMessage]: ...

    def delete(self, message: QueueMessage) -> None: ...

    def depth(self) -> int: ...


class InMemoryJobQueue:
    """Single-process queue with SQS-shaped semantics:

    - `receive` hands out a message and makes it INVISIBLE for
      `visibility_timeout` seconds instead of removing it. If the
      consumer never calls `delete` (it crashed), the message
      reappears after the timeout — at-least-once delivery, the same
      contract the worker must survive against real SQS.
    - `delete` is the ack. Only a delete makes a message truly gone.
    - `depth` counts visible + in-flight messages (SQS splits these
      into two metrics; one number is enough for the backlog check
      and the /ops endpoint at this scale).

    Thread-safe via one lock — uvicorn's threadpool can run requests
    concurrently even in a single process, same reason RateLimiter
    carries one.
    """

    def __init__(self, visibility_timeout: float = 30.0, time_fn=time.monotonic):
        self._visible: deque[str] = deque()
        # receipt -> (job_id, invisible_until)
        self._in_flight: dict[str, tuple[str, float]] = {}
        self._visibility_timeout = visibility_timeout
        self._time_fn = time_fn
        self._lock = threading.Lock()

    def _requeue_expired(self) -> None:
        # Called under the lock. Any in-flight delivery whose
        # visibility window has lapsed goes back to the visible
        # queue — the consumer that held it is presumed dead.
        now = self._time_fn()
        expired = [r for r, (_, until) in self._in_flight.items() if until <= now]
        for receipt in expired:
            job_id, _ = self._in_flight.pop(receipt)
            self._visible.append(job_id)
            logger.warning("job_queue_redelivery job_id=%s", job_id)

    def send(self, job_id: str) -> None:
        with self._lock:
            self._visible.append(job_id)

    def receive(self, max_messages: int = 1) -> list[QueueMessage]:
        with self._lock:
            self._requeue_expired()
            out: list[QueueMessage] = []
            while self._visible and len(out) < max_messages:
                job_id = self._visible.popleft()
                receipt = uuid.uuid4().hex
                self._in_flight[receipt] = (
                    job_id,
                    self._time_fn() + self._visibility_timeout,
                )
                out.append(QueueMessage(job_id=job_id, receipt=receipt))
            return out

    def delete(self, message: QueueMessage) -> None:
        with self._lock:
            # Deleting an unknown/already-expired receipt is a no-op,
            # not an error — same as SQS, where a DeleteMessage with a
            # stale handle succeeds silently. The worker must not die
            # because it acked slightly too late.
            self._in_flight.pop(message.receipt, None)

    def depth(self) -> int:
        with self._lock:
            self._requeue_expired()
            return len(self._visible) + len(self._in_flight)


_queue: JobQueue | None = None
_queue_lock = threading.Lock()


def get_queue() -> JobQueue:
    """Process-wide queue instance. In-memory when INGEST_QUEUE_URL is
    empty (dev/tests); the SQS implementation slots in here on Day 4
    without any caller changing. Resolved lazily at call time — not at
    import — so tests can reconfigure via _reset_for_tests(), same
    seam-shape as s3_store."""
    global _queue
    with _queue_lock:
        if _queue is None:
            settings = get_settings()
            if settings.ingest_queue_url:
                # Day 4 lands SqsJobQueue here. Until then a configured
                # URL is a loud misconfiguration, not a silent fallback.
                raise NotImplementedError(
                    "INGEST_QUEUE_URL is set but the SQS queue backend lands on P4 Day 4"
                )
            _queue = InMemoryJobQueue()
        return _queue


def _reset_for_tests() -> None:
    global _queue
    with _queue_lock:
        _queue = None
