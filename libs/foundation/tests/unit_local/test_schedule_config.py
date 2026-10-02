"""`foundation.resiliant.schedule` contracts: config defaults / validation (twin of the JS
``resolveScheduleConfig``), statuses, kinds, errors."""

from __future__ import annotations

import pytest
from foundation.resiliant.schedule import (
    ACTIVE_SCHEDULE_STATES,
    TERMINAL_SCHEDULE_STATES,
    CronExpressionError,
    ScheduleConfig,
    ScheduleError,
    ScheduleJobKind,
    ScheduleJobStatus,
    resolve_schedule_config,
)


def test_defaults_match_the_js_twin() -> None:
    cfg = ScheduleConfig()
    assert cfg.poll_strategy == 'fixed'
    assert (cfg.fixed_poll_interval_ms, cfg.min_poll_interval_ms, cfg.max_poll_interval_ms) == (30_000, 1_000, 60_000)
    assert cfg.initial_poll_interval_ms == 30_000
    assert (cfg.backoff_growth_factor, cfg.drain_threshold_ratio) == (2, 1)
    assert (cfg.batch_size, cfg.concurrent_workers) == (100, 1)
    assert (cfg.max_retries, cfg.retry_backoff_ms, cfg.claim_timeout_ms) == (3, 30_000, 300_000)
    assert (cfg.enable_metrics, cfg.metrics_log_interval_ms) == (True, 60_000)
    assert cfg.enabled is True


def test_resolve_keeps_overrides_and_ignores_none() -> None:
    cfg = resolve_schedule_config({'batch_size': 7, 'max_retries': None}, retry_backoff_ms=0)
    assert (cfg.batch_size, cfg.max_retries, cfg.retry_backoff_ms) == (7, 3, 0)


@pytest.mark.parametrize(
    'kwargs',
    [
        {'batch_size': 0},
        {'batch_size': 2.5},
        {'concurrent_workers': 0},
        {'max_retries': 0},
        {'fixed_poll_interval_ms': 0},
        {'poll_strategy': 'notify'},  # the scheduler only supports fixed / adaptive
        {'min_poll_interval_ms': 10, 'max_poll_interval_ms': 5},
        {'backoff_growth_factor': 1.0},
        {'claim_timeout_ms': 999},
    ],
)
def test_invalid_config_rejected(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        ScheduleConfig(**kwargs)


def test_statuses_and_kinds() -> None:
    assert ScheduleJobStatus.DONE in TERMINAL_SCHEDULE_STATES
    assert ScheduleJobStatus.SCHEDULED not in TERMINAL_SCHEDULE_STATES
    assert ACTIVE_SCHEDULE_STATES == (ScheduleJobStatus.SCHEDULED, ScheduleJobStatus.RUNNING)
    assert [s.value for s in ScheduleJobStatus] == ['scheduled', 'running', 'done', 'failed', 'cancelled']
    assert [k.value for k in ScheduleJobKind] == ['once', 'interval', 'cron']


def test_cron_expression_error_is_a_schedule_error() -> None:
    error = CronExpressionError('61 * * * *', 'minute 61 is outside 0-59')
    assert isinstance(error, ScheduleError)
    assert str(error) == 'invalid cron expression "61 * * * *": minute 61 is outside 0-59'
