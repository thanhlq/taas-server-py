"""Unit tests for :mod:`foundation.observability.log_throttle`."""

from __future__ import annotations

import logging

import pytest

from foundation.observability.log_throttle import (
    AIOKAFKA_LOGGERS,
    ThrottledLogFilter,
    install_log_throttle,
)


def _record(
    name: str = 'aiokafka',
    msg: str = 'boom %s',
    args: tuple[object, ...] = ('x',),
) -> logging.LogRecord:
    return logging.LogRecord(
        name=name,
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=None,
    )


class _Clock:
    """Monotonic stand-in so tests never sleep."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    c = _Clock()
    monkeypatch.setattr(
        'foundation.observability.log_throttle.time.monotonic', c, raising=True
    )
    return c


def test_first_record_passes(clock: _Clock) -> None:
    f = ThrottledLogFilter(burst=1, interval_seconds=60)
    assert f.filter(_record()) is True


def test_burst_then_suppressed(clock: _Clock) -> None:
    f = ThrottledLogFilter(burst=3, interval_seconds=60)
    assert [f.filter(_record()) for _ in range(5)] == [True, True, True, False, False]


def test_suppressed_count_reported_after_interval(clock: _Clock) -> None:
    f = ThrottledLogFilter(burst=1, interval_seconds=60)
    assert f.filter(_record()) is True
    for _ in range(99):
        f.filter(_record())

    clock.advance(60)
    record = _record()
    assert f.filter(record) is True
    assert '[+99 identical suppressed in the last 60s]' in record.msg


def test_suppression_note_keeps_percent_args_working(clock: _Clock) -> None:
    """The note is appended to the template, so ``%`` args must still apply."""
    template = 'Unable connect to node with id %s'
    f = ThrottledLogFilter(burst=1, interval_seconds=60)
    f.filter(_record(msg=template, args=(1,)))
    f.filter(_record(msg=template, args=(1,)))

    clock.advance(60)
    record = _record(msg=template, args=(7,))
    assert f.filter(record) is True
    assert 'node with id 7' in record.getMessage()
    assert 'identical suppressed' in record.getMessage()


def test_grouping_ignores_interpolated_args(clock: _Clock) -> None:
    """Same template, different node id → one group, not one group per node."""
    f = ThrottledLogFilter(burst=1, interval_seconds=60)
    assert f.filter(_record(msg='node %s down', args=(1,))) is True
    assert f.filter(_record(msg='node %s down', args=(2,))) is False


def test_distinct_messages_are_throttled_independently(clock: _Clock) -> None:
    f = ThrottledLogFilter(burst=1, interval_seconds=60)
    assert f.filter(_record(msg='connect failed')) is True
    assert f.filter(_record(msg='connect failed')) is False
    # A different failure mode is still worth showing immediately.
    assert f.filter(_record(msg='metadata update failed')) is True


def test_distinct_loggers_are_throttled_independently(clock: _Clock) -> None:
    f = ThrottledLogFilter(burst=1, interval_seconds=60)
    assert f.filter(_record(name='aiokafka', msg='same')) is True
    assert f.filter(_record(name='aiokafka.consumer.fetcher', msg='same')) is True


def test_reset_clears_state(clock: _Clock) -> None:
    f = ThrottledLogFilter(burst=1, interval_seconds=60)
    f.filter(_record())
    assert f.filter(_record()) is False
    f.reset()
    assert f.filter(_record()) is True


def test_install_is_idempotent_and_shares_one_filter() -> None:
    """Re-installing must not stack filters, or the budget multiplies."""
    try:
        install_log_throttle(['probe.a', 'probe.b'], burst=1, interval_seconds=60)
        install_log_throttle(['probe.a', 'probe.b'], burst=1, interval_seconds=60)

        for name in ('probe.a', 'probe.b'):
            throttles = [
                f
                for f in logging.getLogger(name).filters
                if isinstance(f, ThrottledLogFilter)
            ]
            assert len(throttles) == 1

        # One shared instance means the burst budget is per message, not per logger.
        a = logging.getLogger('probe.a').filters[0]
        b = logging.getLogger('probe.b').filters[0]
        assert a is b
    finally:
        for name in ('probe.a', 'probe.b'):
            log = logging.getLogger(name)
            for f in list(log.filters):
                log.removeFilter(f)


def test_aiokafka_logger_list_covers_the_observed_noise() -> None:
    """The loggers behind the real broker-restart flood must all be listed."""
    for name in (
        'aiokafka',  # Unable connect to node / Unable to update metadata
        'aiokafka.consumer.fetcher',  # Failed fetch messages from N
        'aiokafka.consumer.group_coordinator',  # Heartbeat / coordinator dead
    ):
        assert name in AIOKAFKA_LOGGERS
