"""Load outbox settings from environment variables."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

from foundation.resiliant.outbox import OutboxConfig, PollStrategy
from foundation.utils.env_utils import get_env


@dataclass
class OutboxSettings:
    """Transactional outbox configuration.

    All values are read from environment variables (prefixed with ``OUTBOX_``)
    and mapped onto an :class:`OutboxConfig` via :meth:`get_config`.
    """

    ENABLED: bool = field(default_factory=get_env('OUTBOX_ENABLED', True))
    """Whether outbox polling is enabled."""

    # Poll strategy: 'fixed', 'adaptive', or 'notify'.
    POLL_STRATEGY: str = field(default_factory=get_env('OUTBOX_POLL_STRATEGY', 'fixed'))
    """Poll strategy: fixed, adaptive, or notify."""

    # Polling configuration
    FIXED_POLL_INTERVAL_MS: int = field(
        default_factory=get_env('OUTBOX_FIXED_POLL_INTERVAL_MS', 3000, int)
    )
    """Sleep interval every cycle when POLL_STRATEGY is 'fixed' (ms)."""
    MIN_POLL_INTERVAL_MS: int = field(
        default_factory=get_env('OUTBOX_MIN_POLL_INTERVAL_MS', 100, int)
    )
    """Minimum polling interval when busy (ms)."""
    MAX_POLL_INTERVAL_MS: int = field(
        default_factory=get_env('OUTBOX_MAX_POLL_INTERVAL_MS', 20000, int)
    )
    """Maximum polling interval when idle (ms)."""
    INITIAL_POLL_INTERVAL_MS: int = field(
        default_factory=get_env('OUTBOX_INITIAL_POLL_INTERVAL_MS', 5000, int)
    )
    """Starting polling interval (ms)."""

    # Adaptive backoff tuning (parsed as float in get_config)
    BACKOFF_GROWTH_FACTOR: str = field(
        default_factory=get_env('OUTBOX_BACKOFF_GROWTH_FACTOR', '3.0')
    )
    """Decorrelated jitter growth factor (must be > 1.0)."""
    DRAIN_THRESHOLD_RATIO: str = field(
        default_factory=get_env('OUTBOX_DRAIN_THRESHOLD_RATIO', '1.0')
    )
    """Skip sleep and poll again when fetched >= batch_size * ratio."""

    # NOTIFY strategy (Postgres LISTEN/NOTIFY)
    NOTIFY_CHANNEL: str = field(
        default_factory=get_env('OUTBOX_NOTIFY_CHANNEL', 'outbox_new_event')
    )
    """Postgres LISTEN/NOTIFY channel name."""
    NOTIFY_DSN: str = field(default_factory=get_env('OUTBOX_NOTIFY_DSN', ''))
    """Optional asyncpg DSN for the LISTEN connection (empty means in-process only)."""

    # Batch processing
    BATCH_SIZE: int = field(default_factory=get_env('OUTBOX_BATCH_SIZE', 100, int))
    """Number of events to fetch per poll."""
    CONCURRENT_WORKERS: int = field(
        default_factory=get_env('OUTBOX_CONCURRENT_WORKERS', 1, int)
    )
    """Number of concurrent poller workers."""

    # Retry configuration
    MAX_RETRIES: int = field(default_factory=get_env('OUTBOX_MAX_RETRIES', 3, int))
    """Maximum retry attempts before moving to DLQ."""
    RETRY_BACKOFF_MULTIPLIER: str = field(
        default_factory=get_env('OUTBOX_RETRY_BACKOFF_MULTIPLIER', '2.0')
    )
    """Exponential backoff multiplier for retries (parsed as float in get_config)."""
    PROCESSING_TIMEOUT_SECONDS: int = field(
        default_factory=get_env('OUTBOX_PROCESSING_TIMEOUT_SECONDS', 30, int)
    )
    """Timeout for processing events (seconds)."""

    # Database optimizations
    USE_SKIP_LOCKED: bool = field(
        default_factory=get_env('OUTBOX_USE_SKIP_LOCKED', True)
    )
    """Use FOR UPDATE SKIP LOCKED in queries."""
    USE_READ_REPLICA: bool = field(
        default_factory=get_env('OUTBOX_USE_READ_REPLICA', False)
    )
    """Use read replica for initial queries."""

    # Archiving configuration
    ARCHIVE_AFTER_DAYS: int = field(
        default_factory=get_env('OUTBOX_ARCHIVE_AFTER_DAYS', 7, int)
    )
    """Move published events to archive after N days."""
    CLEANUP_ARCHIVE_AFTER_DAYS: int = field(
        default_factory=get_env('OUTBOX_CLEANUP_ARCHIVE_AFTER_DAYS', 30, int)
    )
    """Delete archived events after N days."""

    # Monitoring
    ENABLE_METRICS: bool = field(
        default_factory=get_env('OUTBOX_ENABLE_METRICS', True)
    )
    """Enable metrics collection."""
    METRICS_LOG_INTERVAL_SECONDS: int = field(
        default_factory=get_env('OUTBOX_METRICS_LOG_INTERVAL_SECONDS', 60, int)
    )
    """Interval between metrics log emissions (seconds)."""

    # Connection pool
    DB_POOL_MIN_SIZE: int = field(
        default_factory=get_env('OUTBOX_DB_POOL_MIN_SIZE', 5, int)
    )
    """Minimum database connection pool size."""
    DB_POOL_MAX_SIZE: int = field(
        default_factory=get_env('OUTBOX_DB_POOL_MAX_SIZE', 20, int)
    )
    """Maximum database connection pool size."""
    DB_QUERY_TIMEOUT_MS: int = field(
        default_factory=get_env('OUTBOX_DB_QUERY_TIMEOUT_MS', 5000, int)
    )
    """Database query timeout (ms)."""

    def get_config(self) -> OutboxConfig:
        """Return the validated :class:`OutboxConfig`.

        Returns:
            The outbox configuration.
        """
        return OutboxConfig(
            enabled=self.ENABLED,
            poll_strategy=cast(PollStrategy, self.POLL_STRATEGY),
            fixed_poll_interval_ms=self.FIXED_POLL_INTERVAL_MS,
            min_poll_interval_ms=self.MIN_POLL_INTERVAL_MS,
            max_poll_interval_ms=self.MAX_POLL_INTERVAL_MS,
            initial_poll_interval_ms=self.INITIAL_POLL_INTERVAL_MS,
            backoff_growth_factor=float(self.BACKOFF_GROWTH_FACTOR),
            drain_threshold_ratio=float(self.DRAIN_THRESHOLD_RATIO),
            notify_channel=self.NOTIFY_CHANNEL,
            notify_dsn=self.NOTIFY_DSN or None,
            batch_size=self.BATCH_SIZE,
            concurrent_workers=self.CONCURRENT_WORKERS,
            max_retries=self.MAX_RETRIES,
            retry_backoff_multiplier=float(self.RETRY_BACKOFF_MULTIPLIER),
            processing_timeout_seconds=self.PROCESSING_TIMEOUT_SECONDS,
            use_skip_locked=self.USE_SKIP_LOCKED,
            use_read_replica=self.USE_READ_REPLICA,
            archive_after_days=self.ARCHIVE_AFTER_DAYS,
            cleanup_archive_after_days=self.CLEANUP_ARCHIVE_AFTER_DAYS,
            enable_metrics=self.ENABLE_METRICS,
            metrics_log_interval_seconds=self.METRICS_LOG_INTERVAL_SECONDS,
            db_pool_min_size=self.DB_POOL_MIN_SIZE,
            db_pool_max_size=self.DB_POOL_MAX_SIZE,
            db_query_timeout_ms=self.DB_QUERY_TIMEOUT_MS,
        )


def build_outbox_config(settings: OutboxSettings | None = None) -> OutboxConfig:
    """Build the internal (validated) :class:`OutboxConfig` from settings.

    Args:
        settings: Optional settings instance. When omitted, a fresh
            :class:`OutboxSettings` is read from the environment.

    Returns:
        The outbox configuration.
    """
    return (settings or OutboxSettings()).get_config()

