"""
P4 Day 4 — SqsJobQueue against moto's fake SQS.

These are the SAME behavioural claims test_job_queue.py pins on the
in-memory fake, re-proven against the real boto3 call surface — the
point of having one JobQueue interface is that the worker cannot tell
the two apart, and this file is the evidence. No real AWS anywhere:
moto intercepts in-process (same approach as the P2 Day-4 S3 tests).
"""

import boto3
import pytest
from moto import mock_aws

from narration_enrichment import config, job_queue
from narration_enrichment.job_queue import QueueMessage, SqsJobQueue

REGION = "us-east-1"


@pytest.fixture()
def sqs_queue_url():
    with mock_aws():
        client = boto3.client("sqs", region_name=REGION)
        # VisibilityTimeout=1 so the redelivery test waits one real
        # second, not SQS's 30-second default. (moto honours the
        # attribute; unlike the in-memory fake there is no injectable
        # clock on the real service, so one second is the honest cost
        # of proving the behaviour.)
        resp = client.create_queue(
            QueueName="narration-ingest-test",
            Attributes={"VisibilityTimeout": "1"},
        )
        yield resp["QueueUrl"]


@pytest.fixture(autouse=True)
def _aws_creds(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    yield


def test_send_receive_round_trip(sqs_queue_url):
    q = SqsJobQueue(sqs_queue_url, REGION)
    q.send("job-1")

    messages = q.receive()

    assert len(messages) == 1
    assert messages[0].job_id == "job-1"
    assert messages[0].receipt


def test_received_message_is_invisible_until_timeout(sqs_queue_url):
    q = SqsJobQueue(sqs_queue_url, REGION)
    q.send("job-1")
    q.receive()

    assert q.receive() == []


def test_unacked_message_redelivers_with_fresh_receipt(sqs_queue_url):
    import time

    q = SqsJobQueue(sqs_queue_url, REGION)
    q.send("job-1")
    first = q.receive()[0]

    time.sleep(1.1)  # cross the 1s VisibilityTimeout set on the fixture queue
    redelivered = q.receive()

    assert len(redelivered) == 1
    assert redelivered[0].job_id == "job-1"
    assert redelivered[0].receipt != first.receipt


def test_delete_acks_permanently(sqs_queue_url):
    import time

    q = SqsJobQueue(sqs_queue_url, REGION)
    q.send("job-1")
    msg = q.receive()[0]

    q.delete(msg)
    time.sleep(1.1)

    assert q.receive() == []
    assert q.depth() == 0


def test_depth_counts_visible_plus_in_flight(sqs_queue_url):
    q = SqsJobQueue(sqs_queue_url, REGION)
    q.send("job-1")
    q.send("job-2")
    assert q.depth() == 2

    msg = q.receive()[0]  # one in flight, one visible
    assert q.depth() == 2

    q.delete(msg)
    assert q.depth() == 1


def test_receive_batches_up_to_max_messages(sqs_queue_url):
    q = SqsJobQueue(sqs_queue_url, REGION)
    for i in range(3):
        q.send(f"job-{i}")

    batch = q.receive(max_messages=10)

    # SQS makes no FIFO promise on a standard queue — assert the SET,
    # not the order (the in-memory fake is stricter than the real
    # thing here, which is the safe direction for tests to differ).
    assert {m.job_id for m in batch} == {"job-0", "job-1", "job-2"}


def test_get_queue_factory_returns_sqs_backend_when_url_configured(sqs_queue_url, monkeypatch):
    monkeypatch.setenv("INGEST_QUEUE_URL", sqs_queue_url)
    monkeypatch.setenv("AWS_REGION", REGION)
    config.get_settings.cache_clear()
    job_queue._reset_for_tests()
    try:
        q = job_queue.get_queue()

        assert isinstance(q, SqsJobQueue)
        # And it actually talks to the configured queue, end to end
        # through the factory — not just the right class name.
        q.send("job-via-factory")
        assert q.receive()[0].job_id == "job-via-factory"
    finally:
        config.get_settings.cache_clear()
        job_queue._reset_for_tests()
