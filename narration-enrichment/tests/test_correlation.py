"""
Unit tests for correlation.py — the ContextVar + logging.Filter pair,
in isolation from FastAPI/Starlette entirely.
"""

import io
import logging

from narration_enrichment.correlation import (
    CorrelationIdLogFilter,
    get_correlation_id,
    new_correlation_id,
    set_correlation_id,
)


def test_default_correlation_id_is_none_when_nothing_has_been_set():
    # A fresh test process/thread that never went through the middleware —
    # this is what a log line from outside any request looks like.
    assert get_correlation_id() == "none"


def test_set_and_get_round_trip():
    set_correlation_id("abc-123")
    assert get_correlation_id() == "abc-123"
    set_correlation_id("none")  # restore, since the ContextVar is module-level


def test_new_correlation_id_returns_a_plausible_uuid():
    value = new_correlation_id()
    assert len(value) == 36  # standard UUID4 string length, incl. hyphens
    assert value.count("-") == 4


def test_log_filter_attaches_the_current_correlation_id_to_the_record():
    set_correlation_id("filter-test-id")
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="hello", args=(), exc_info=None,
    )

    result = CorrelationIdLogFilter().filter(record)

    assert result is True
    assert record.correlation_id == "filter-test-id"
    set_correlation_id("none")  # restore


def test_a_filter_on_the_logger_itself_does_not_reach_a_child_loggers_records():
    # Real bug this project actually hit: logging.Logger.filter() is only
    # invoked by the logger that ORIGINATES a record — propagation to an
    # ancestor logger calls that ancestor's HANDLERS directly, bypassing
    # the ancestor's own filter() method entirely. A filter attached via
    # logger.addFilter() therefore silently never runs for messages
    # logged through any other (e.g. child) logger. This test pins that
    # behavior down directly, rather than trusting it as a comment.
    #
    # Uses a private, isolated logger tree (not the real root logger) —
    # the real one already has main.py's own (correct) fix wired into
    # its handler by the time the test suite has imported main.py once,
    # which would silently mask this exact bug if reproduced against it.
    parent = logging.getLogger("test_isolated_wrong_place_parent")
    child = logging.getLogger("test_isolated_wrong_place_parent.child")
    parent.setLevel(logging.WARNING)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(correlation_id)s %(message)s"))
    parent.addHandler(handler)
    wrong_filter = CorrelationIdLogFilter()
    parent.addFilter(wrong_filter)  # the WRONG place, deliberately
    set_correlation_id("should-not-appear")

    # The bug manifests as Python's logging module internally catching a
    # KeyError in Handler.emit() and printing "--- Logging error ---" to
    # stderr — it does not raise up to the caller.
    child.warning("a message from a child logger")

    output = stream.getvalue()
    # Record never got .correlation_id, so formatting failed and nothing
    # correctly formatted made it into the stream.
    assert "should-not-appear" not in output

    parent.removeHandler(handler)
    parent.removeFilter(wrong_filter)
    set_correlation_id("none")


def test_a_filter_on_the_handler_correctly_reaches_a_child_loggers_records():
    # The actual fix main.py uses: attach the filter to the HANDLER, not
    # the logger — Handler.handle() checks its own filters regardless of
    # which logger the record originated from. Same isolated-tree
    # reasoning as the test above.
    parent = logging.getLogger("test_isolated_right_place_parent")
    child = logging.getLogger("test_isolated_right_place_parent.child")
    parent.setLevel(logging.WARNING)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(correlation_id)s %(message)s"))
    handler.addFilter(CorrelationIdLogFilter())  # the RIGHT place
    parent.addHandler(handler)
    set_correlation_id("should-appear")

    child.warning("a message from a child logger")

    output = stream.getvalue()
    assert "should-appear a message from a child logger" in output

    parent.removeHandler(handler)
    set_correlation_id("none")
