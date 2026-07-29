"""Tests for `foundation.resiliant.schedule.ScheduleConfig` validation."""

from __future__ import annotations

import pytest
from foundation.resiliant.schedule import (
    ScheduleConfig,
    ScheduleJobKind,
    ScheduleJobStatus,
    TERMINAL_SCHEDULE_STATES,
)


def test_defaults_are_valid() -> None:
    cfg = ScheduleConfig()
    assert cfg.enabled is True
    assert cfg.poll_strategy == 'fixed'
    assert cfg.batch_size >= 1


@pytest.mark.parametrize(
    'kwargs',
    [
        {'batch_size': 0},
        {'concurrent_workers': 0},
        {'poll_strategy': 'notify'},  # scheduler only supports fixed/adaptive
        {'min_poll_interval_ms': 10, 'max_poll_interval_ms': 5},
        {'backoff_growth_factor': 1.0},
    ],
)
def test_invalid_config_rejected(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        ScheduleConfig(**kwargs)


def test_terminal_states() -> None:
    assert ScheduleJobStatus.DONE in TERMINAL_SCHEDULE_STATES
    assert ScheduleJobStatus.SCHEDULED not in TERMINAL_SCHEDULE_STATES
    assert set(ScheduleJobKind) == {
        ScheduleJobKind.ONCE,
        ScheduleJobKind.INTERVAL,
        ScheduleJobKind.CRON,
    }
