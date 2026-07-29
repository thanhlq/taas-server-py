"""Load scheduler settings from environment variables (``SCHEDULER_`` prefix)."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from foundation.resiliant.schedule import ScheduleConfig
from foundation.utils.env_utils import get_env


@dataclass
class ScheduleSettings:
    """Durable-timer / scheduler configuration.

    All values are read from environment variables (prefixed with
    ``SCHEDULER_``) and mapped onto a :class:`ScheduleConfig` via
    :meth:`get_config`.
    """

    ENABLED: bool = field(default_factory=get_env('SCHEDULER_ENABLED', True))
    POLL_STRATEGY: str = field(
        default_factory=get_env('SCHEDULER_POLL_STRATEGY', 'fixed')
    )

    FIXED_POLL_INTERVAL_MS: int = field(
        default_factory=get_env('SCHEDULER_FIXED_POLL_INTERVAL_MS', 30_000, int)
    )
    MIN_POLL_INTERVAL_MS: int = field(
        default_factory=get_env('SCHEDULER_MIN_POLL_INTERVAL_MS', 1_000, int)
    )
    MAX_POLL_INTERVAL_MS: int = field(
        default_factory=get_env('SCHEDULER_MAX_POLL_INTERVAL_MS', 60_000, int)
    )
    INITIAL_POLL_INTERVAL_MS: int = field(
        default_factory=get_env('SCHEDULER_INITIAL_POLL_INTERVAL_MS', 30_000, int)
    )
    BACKOFF_GROWTH_FACTOR: str = field(
        default_factory=get_env('SCHEDULER_BACKOFF_GROWTH_FACTOR', '2.0')
    )
    DRAIN_THRESHOLD_RATIO: str = field(
        default_factory=get_env('SCHEDULER_DRAIN_THRESHOLD_RATIO', '1.0')
    )

    BATCH_SIZE: int = field(default_factory=get_env('SCHEDULER_BATCH_SIZE', 100, int))
    CONCURRENT_WORKERS: int = field(
        default_factory=get_env('SCHEDULER_CONCURRENT_WORKERS', 1, int)
    )

    MAX_RETRIES: int = field(default_factory=get_env('SCHEDULER_MAX_RETRIES', 3, int))
    RETRY_BACKOFF_SECONDS: str = field(
        default_factory=get_env('SCHEDULER_RETRY_BACKOFF_SECONDS', '30.0')
    )
    CLAIM_TIMEOUT_SECONDS: int = field(
        default_factory=get_env('SCHEDULER_CLAIM_TIMEOUT_SECONDS', 300, int)
    )

    USE_SKIP_LOCKED: bool = field(
        default_factory=get_env('SCHEDULER_USE_SKIP_LOCKED', True)
    )

    ENABLE_METRICS: bool = field(
        default_factory=get_env('SCHEDULER_ENABLE_METRICS', True)
    )
    METRICS_LOG_INTERVAL_SECONDS: int = field(
        default_factory=get_env('SCHEDULER_METRICS_LOG_INTERVAL_SECONDS', 60, int)
    )

    def get_config(self) -> ScheduleConfig:
        """Return the validated :class:`ScheduleConfig`."""
        return ScheduleConfig(
            enabled=self.ENABLED,
            poll_strategy=self.POLL_STRATEGY,
            fixed_poll_interval_ms=self.FIXED_POLL_INTERVAL_MS,
            min_poll_interval_ms=self.MIN_POLL_INTERVAL_MS,
            max_poll_interval_ms=self.MAX_POLL_INTERVAL_MS,
            initial_poll_interval_ms=self.INITIAL_POLL_INTERVAL_MS,
            backoff_growth_factor=float(self.BACKOFF_GROWTH_FACTOR),
            drain_threshold_ratio=float(self.DRAIN_THRESHOLD_RATIO),
            batch_size=self.BATCH_SIZE,
            concurrent_workers=self.CONCURRENT_WORKERS,
            max_retries=self.MAX_RETRIES,
            retry_backoff_seconds=float(self.RETRY_BACKOFF_SECONDS),
            claim_timeout_seconds=self.CLAIM_TIMEOUT_SECONDS,
            use_skip_locked=self.USE_SKIP_LOCKED,
            enable_metrics=self.ENABLE_METRICS,
            metrics_log_interval_seconds=self.METRICS_LOG_INTERVAL_SECONDS,
        )


@lru_cache(maxsize=1)
def get_schedule_config(settings: ScheduleSettings | None = None) -> ScheduleConfig:
    """Build the validated :class:`ScheduleConfig` from settings/environment."""
    return (settings or ScheduleSettings()).get_config()
