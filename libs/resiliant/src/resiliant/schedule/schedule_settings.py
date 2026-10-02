"""
Scheduler settings from the environment — same variables as ``@taas/foundation``
``ResiliantSettings.scheduleConfig``.

| Variable | Default | ``ScheduleConfig`` field |
| --- | --- | --- |
| ``SCHEDULE_POLL_STRATEGY`` | ``fixed`` | ``poll_strategy`` (``fixed`` / ``adaptive``) |
| ``SCHEDULE_FIXED_POLL_INTERVAL_MS`` | ``30000`` | ``fixed_poll_interval_ms`` |
| ``SCHEDULE_MIN_POLL_INTERVAL_MS`` / ``SCHEDULE_MAX_POLL_INTERVAL_MS`` | ``1000`` / ``60000`` | adaptive bounds |
| ``SCHEDULE_BATCH_SIZE`` | ``100`` | ``batch_size`` |
| ``SCHEDULE_CONCURRENT_WORKERS`` | ``1`` | ``concurrent_workers`` |
| ``SCHEDULE_MAX_RETRIES`` | ``3`` | ``max_retries`` (default per new job) |
| ``SCHEDULE_RETRY_BACKOFF_MS`` | ``30000`` | ``retry_backoff_ms`` |
| ``SCHEDULE_CLAIM_TIMEOUT_MS`` | ``300000`` | ``claim_timeout_ms`` (stale lease reset) |
| ``SCHEDULE_ENABLED`` (Python only) | ``true`` | ``enabled`` (worker hosts the poller) |

Unset or blank means the default. A malformed value (a number that does not parse,
an unknown strategy, a non-boolean) raises ``ValueError`` — never a silent default.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from foundation.resiliant.schedule import ScheduleConfig, resolve_schedule_config

_TRUE = frozenset({'true', '1', 'yes', 'on'})
_FALSE = frozenset({'false', '0', 'no', 'off'})


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


class ScheduleSettings:
    """Typed view over a settings source (default ``os.environ``)."""

    def __init__(self, source: Mapping[str, Any] | None = None) -> None:
        self._source: Mapping[str, Any] = os.environ if source is None else source

    def _num(self, key: str) -> int | float | None:
        value = self._source.get(key)
        if _blank(value):
            return None
        if isinstance(value, bool):
            raise ValueError(f'{key} must be a number, got {value!r}')
        if isinstance(value, int | float):
            number: float = value
        else:
            try:
                number = float(str(value).strip())
            except ValueError as exc:
                raise ValueError(f'{key} must be a number, got {value!r}') from exc
        if number != number:  # NaN
            raise ValueError(f'{key} must be a number, got {value!r}')
        return int(number) if float(number).is_integer() else number

    def _bool(self, key: str) -> bool | None:
        value = self._source.get(key)
        if _blank(value):
            return None
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
        raise ValueError(f'{key} must be a boolean, got "{value}"')

    def _str(self, key: str) -> str | None:
        value = self._source.get(key)
        return None if _blank(value) else str(value)

    def schedule_config(self, **overrides: Any) -> ScheduleConfig:
        """The validated :class:`ScheduleConfig`; ``overrides`` win over the environment."""
        return resolve_schedule_config(
            {
                'poll_strategy': self._str('SCHEDULE_POLL_STRATEGY'),
                'fixed_poll_interval_ms': self._num('SCHEDULE_FIXED_POLL_INTERVAL_MS'),
                'min_poll_interval_ms': self._num('SCHEDULE_MIN_POLL_INTERVAL_MS'),
                'max_poll_interval_ms': self._num('SCHEDULE_MAX_POLL_INTERVAL_MS'),
                'batch_size': self._num('SCHEDULE_BATCH_SIZE'),
                'concurrent_workers': self._num('SCHEDULE_CONCURRENT_WORKERS'),
                'max_retries': self._num('SCHEDULE_MAX_RETRIES'),
                'retry_backoff_ms': self._num('SCHEDULE_RETRY_BACKOFF_MS'),
                'claim_timeout_ms': self._num('SCHEDULE_CLAIM_TIMEOUT_MS'),
                'enabled': self._bool('SCHEDULE_ENABLED'),
            },
            **overrides,
        )


@lru_cache(maxsize=1)
def get_schedule_config() -> ScheduleConfig:
    """The process-wide :class:`ScheduleConfig` from the environment (cached)."""
    return ScheduleSettings().schedule_config()


__all__ = ['ScheduleSettings', 'get_schedule_config']
