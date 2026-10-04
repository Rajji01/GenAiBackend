"""
P4 Day 2 — unit tests for the in-memory job queue.

Pure in-process: no FastAPI, no DB, no network. The clock is injected
(same pattern as test_rate_limiter.py) so the visibility-timeout
behaviour — the one piece of real SQS semantics the fake must get
right for the Day-3 worker to be written against honest contracts —
is proven without a real 30-second sleep.
"""

from narration_enrichment.job_queue import InMemoryJobQueue, QueueMessage


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _queue(visibility_timeout: float = 30.0) -> tuple[InMemoryJobQueue, FakeClock]:
    clock = FakeClock()
    return InMemoryJobQueue(visibility_timeout=visibility_timeout, time_fn=clock), clock


def test_send_then_receive_returns_the_message():
    q, _ = _queue()
    q.send("job-1")

    messages = q.receive()

    assert len(messages) == 1
    assert messages[0].job_id == "job-1"
    assert messages[0].receipt  # a delivery handle, not empty


def test_receive_on_empty_queue_returns_empty_list():
    q, _ = _queue()

    assert q.receive() == []


def test_received_message_is_invisible_to_a_second_receive():
    # At-least-once, not at-twice-concurrently: while one consumer
    # holds the message inside its visibility window, no other
    # receive() hands out the same job.
    q, _ = _queue()
    q.send("job-1")
    q.receive()

    assert q.receive() == []


def test_deleted_message_never_comes_back_even_after_timeout():
    q, clock = _queue(visibility_timeout=30.0)
    q.send("job-1")
    msg = q.receive()[0]

    q.delete(msg)
    clock.advance(31.0)

    assert q.receive() == []
    assert q.depth() == 0


def test_unacked_message_is_redelivered_after_visibility_timeout():
    # The consumer crashed mid-work: it received but never deleted.
    # After the window lapses the message must reappear — this is the
    # exact contract the Day-3 worker's CAS claim has to survive.
    q, clock = _queue(visibility_timeout=30.0)
    q.send("job-1")
    first = q.receive()[0]

    clock.advance(31.0)
    redelivered = q.receive()

    assert len(redelivered) == 1
    assert redelivered[0].job_id == "job-1"
    # A re-delivery is a NEW delivery: fresh receipt, like SQS's fresh
    # ReceiptHandle. The dead consumer's old handle must not alias it.
    assert redelivered[0].receipt != first.receipt


def test_message_stays_invisible_inside_the_window():
    q, clock = _queue(visibility_timeout=30.0)
    q.send("job-1")
    q.receive()

    clock.advance(29.0)

    assert q.receive() == []


def test_delete_with_stale_receipt_is_a_silent_no_op():
    # SQS semantics: acking after your visibility window expired (and
    # the message was redelivered to someone else) succeeds silently.
    # A worker must not crash for acking slightly too late.
    q, clock = _queue(visibility_timeout=30.0)
    q.send("job-1")
    old = q.receive()[0]
    clock.advance(31.0)
    fresh = q.receive()[0]

    q.delete(old)  # stale handle — no error, and no effect on the fresh delivery

    assert q.depth() == 1  # the fresh in-flight delivery still counts
    q.delete(fresh)
    assert q.depth() == 0


def test_receive_batches_up_to_max_messages_in_fifo_order():
    q, _ = _queue()
    for i in range(3):
        q.send(f"job-{i}")

    batch = q.receive(max_messages=2)

    assert [m.job_id for m in batch] == ["job-0", "job-1"]
    assert q.receive(max_messages=2)[0].job_id == "job-2"


def test_depth_counts_visible_plus_in_flight():
    q, _ = _queue()
    q.send("job-1")
    q.send("job-2")
    assert q.depth() == 2

    msg = q.receive()[0]  # one in flight, one visible
    assert q.depth() == 2

    q.delete(msg)
    assert q.depth() == 1


def test_delete_accepts_a_reconstructed_message_value():
    # QueueMessage is a frozen dataclass — delete must key off the
    # receipt value, not object identity, or a worker that serialized
    # the handle across a boundary couldn't ack.
    q, _ = _queue()
    q.send("job-1")
    msg = q.receive()[0]

    q.delete(QueueMessage(job_id=msg.job_id, receipt=msg.receipt))

    assert q.depth() == 0
