"""
🔇 Log throttling for noisy third-party loggers.

Some client libraries log one ERROR *per retry attempt*. When the remote
service is down — a Kafka broker restart, a Redis failover — their internal
retry loops turn a single fault into thousands of identical lines, which
buries every other log in the process.

:class:`ThrottledLogFilter` collapses those bursts: the first few records of
each distinct message pass through untouched, the rest are counted and
dropped, and once per interval one record is let through carrying a
``[+N suppressed ...]`` suffix so the reader can still see the fault is
ongoing.

Grouping is by ``(logger name, level, message template)`` — the template
*before* ``%`` args are applied — so "Unable connect to node with id 1" and
"... id 2" collapse into one group instead of one per broker.

Usage::

    install_log_throttle(['aiokafka'], burst=3, interval_seconds=60)
"""

from __future__ import annotations

import logging
import threading
import time

DEFAULT_BURST = 1
"""
Records let through per group before suppression kicks in.

One is usually right: a fault surfaces as several *distinct* messages (connect
failed, metadata failed, fetch failed, coordinator dead), so a burst of 1 still
yields a handful of informative lines — just not the same line repeated.
"""

DEFAULT_INTERVAL_SECONDS = 60.0
"""How long a suppression window lasts before one record is let through again."""


class _GroupState:
    """Per-message-group throttling counters."""

    __slots__ = ('window_start', 'emitted', 'suppressed')

    def __init__(self, window_start: float, emitted: int = 0) -> None:
        self.window_start = window_start
        """``time.monotonic()`` when the current window opened."""
        self.emitted = emitted
        """Records let through in the current window."""
        self.suppressed = 0
        """Records dropped in the current window."""


class ThrottledLogFilter(logging.Filter):
    """
    Rate-limit repeated log records, keeping a count of what was dropped.

    Attach to a *logger* (not a handler) so suppressed records never reach any
    handler — including the file and OTLP adapters, which would otherwise ship
    the full flood off-box.

    Note filters do **not** inherit down the logger hierarchy: a filter on
    ``aiokafka`` is not consulted for ``aiokafka.consumer.fetcher`` records.
    Use :func:`install_log_throttle`, which walks the known child loggers.
    """

    def __init__(
        self,
        burst: int = DEFAULT_BURST,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
    ) -> None:
        super().__init__('')
        self.burst = max(1, burst)
        """Records to emit per group before suppressing the remainder."""
        self.interval_seconds = max(0.0, interval_seconds)
        """Seconds a group stays suppressed before one record is let through."""
        self._state: dict[tuple[str, int, str], _GroupState] = {}
        self._lock = threading.Lock()

    def filter(self, record: logging.LogRecord) -> bool:
        """Return True to emit the record, False to drop it."""
        key = (record.name, record.levelno, str(record.msg))
        now = time.monotonic()

        with self._lock:
            state = self._state.get(key)

            if state is None:
                self._state[key] = _GroupState(window_start=now, emitted=1)
                return True

            if now - state.window_start >= self.interval_seconds:
                # New window. Report what the previous one swallowed, so a
                # persistent fault stays visible without being loud.
                suppressed = state.suppressed
                self._state[key] = _GroupState(window_start=now, emitted=1)
                if suppressed:
                    _annotate_suppressed(record, suppressed, self.interval_seconds)
                return True

            if state.emitted < self.burst:
                state.emitted += 1
                return True

            state.suppressed += 1
            return False

    def reset(self) -> None:
        """Forget all throttling state (used by tests, and on reconnect)."""
        with self._lock:
            self._state.clear()


def _annotate_suppressed(
    record: logging.LogRecord, suppressed: int, interval_seconds: float
) -> None:
    """
    Append a suppression note to ``record``.

    Mutates ``record.msg`` rather than ``record.getMessage()`` so ``%``-style
    args still apply. The suffix is deliberately ``%``-free — it is appended to
    a format template that is about to be interpolated.
    """
    record.msg = (
        f'{record.msg} [+{suppressed} identical suppressed in the last '
        f'{interval_seconds:.0f}s]'
    )


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------

# aiokafka spreads its logging over a module-per-logger tree plus one literal
# 'aiokafka' logger in client.py. Filters are not inherited by child loggers,
# so every name that emits retry noise has to be listed. Names are stable
# across aiokafka releases; an entry that no longer exists is harmless.
AIOKAFKA_LOGGERS: tuple[str, ...] = (
    'aiokafka',
    'aiokafka.client',
    'aiokafka.cluster',
    'aiokafka.conn',
    'aiokafka.consumer.consumer',
    'aiokafka.consumer.fetcher',
    'aiokafka.consumer.group_coordinator',
    'aiokafka.consumer.subscription_state',
    'aiokafka.producer.producer',
    'aiokafka.producer.sender',
    'aiokafka.admin.client',
)


def install_log_throttle(
    logger_names: tuple[str, ...] | list[str],
    burst: int = DEFAULT_BURST,
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
) -> ThrottledLogFilter:
    """
    Attach one shared :class:`ThrottledLogFilter` to each named logger.

    A single filter instance is shared so the burst budget is per *message*,
    not per logger — otherwise each of the ~11 aiokafka loggers would get its
    own allowance and the flood would be 11x the intended volume.

    Idempotent: calling twice does not stack filters. ``getLogger`` is used to
    create the loggers eagerly, so this works whether or not the third-party
    package has been imported yet.
    """
    throttle = ThrottledLogFilter(burst=burst, interval_seconds=interval_seconds)

    for name in logger_names:
        logger = logging.getLogger(name)
        existing = [f for f in logger.filters if isinstance(f, ThrottledLogFilter)]
        for stale in existing:
            logger.removeFilter(stale)
        logger.addFilter(throttle)

    return throttle


def install_aiokafka_log_throttle(
    burst: int = DEFAULT_BURST,
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
) -> ThrottledLogFilter:
    """Throttle aiokafka's per-retry connection/metadata ERROR spam."""
    return install_log_throttle(
        AIOKAFKA_LOGGERS, burst=burst, interval_seconds=interval_seconds
    )
