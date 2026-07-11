"""Load dead letter queue (DLQ) settings from environment variables."""

from __future__ import annotations

from dataclasses import dataclass, field

from foundation.resiliant.dlq import DeadLetterConfig
from foundation.utils.env_utils import get_env


@dataclass
class DlqSettings:
    """Dead letter queue configuration.

    All values are read from environment variables (prefixed with ``DLQ_``)
    and mapped onto a :class:`DeadLetterConfig` via :meth:`get_config`.
    """

    ENABLED: bool = field(default_factory=get_env('DLQ_ENABLED', True))
    """Enable or disable DLQ functionality globally."""

    # Polling configuration
    POLL_INTERVAL_MS: int = field(
        default_factory=get_env('DLQ_POLL_INTERVAL_MS', 5000, int)
    )
    """Base polling interval in milliseconds."""
    INITIAL_POLL_INTERVAL_MS: int = field(
        default_factory=get_env('DLQ_INITIAL_POLL_INTERVAL_MS', 1000, int)
    )
    """Initial interval for adaptive polling (ms)."""
    MAX_POLL_INTERVAL_MS: int = field(
        default_factory=get_env('DLQ_MAX_POLL_INTERVAL_MS', 30000, int)
    )
    """Maximum interval for adaptive polling (ms)."""
    BATCH_SIZE: int = field(default_factory=get_env('DLQ_BATCH_SIZE', 50, int))
    """Number of events to fetch and process per poll."""
    CONCURRENT_WORKERS: int = field(
        default_factory=get_env('DLQ_CONCURRENT_WORKERS', 2, int)
    )
    """Number of concurrent retry workers."""

    # Retry configuration
    MAX_RETRIES: int = field(default_factory=get_env('DLQ_MAX_RETRIES', 3, int))
    """Default maximum retry attempts per event."""
    RETRY_BACKOFF_MULTIPLIER: str = field(
        default_factory=get_env('DLQ_RETRY_BACKOFF_MULTIPLIER', '2.0')
    )
    """Multiplier for exponential backoff (parsed as float in get_config)."""
    RETRY_MAX_INTERVAL_MS: int = field(
        default_factory=get_env('DLQ_RETRY_MAX_INTERVAL_MS', 60000, int)
    )
    """Maximum interval between retries (ms)."""

    # Database configuration
    USE_SKIP_LOCKED: bool = field(
        default_factory=get_env('DLQ_USE_SKIP_LOCKED', True)
    )
    """Use FOR UPDATE SKIP LOCKED for concurrent safety."""

    # Archive configuration
    ARCHIVE_AFTER_DAYS: int = field(
        default_factory=get_env('DLQ_ARCHIVE_AFTER_DAYS', 30, int)
    )
    """Archive events older than this many days."""
    AUTO_ARCHIVE_ENABLED: bool = field(
        default_factory=get_env('DLQ_AUTO_ARCHIVE_ENABLED', True)
    )
    """Enable automatic archiving of old events."""

    # Metrics configuration
    ENABLE_METRICS: bool = field(
        default_factory=get_env('DLQ_ENABLE_METRICS', True)
    )
    """Enable metrics collection and reporting."""

    # Handler-specific retry configuration
    HANDLER_RETRY_ENABLED: bool = field(
        default_factory=get_env('DLQ_HANDLER_RETRY_ENABLED', True)
    )
    """Enable handler-specific retry logic."""
    HANDLER_MAX_RETRIES: dict[str, int] = field(
        default_factory=get_env('DLQ_HANDLER_MAX_RETRIES', {}, dict[str, int])
    )
    """Per-handler maximum retry limits (JSON or comma-separated ``name:limit``)."""

    def get_config(self) -> DeadLetterConfig:
        """Return the :class:`DeadLetterConfig`.

        Returns:
            The dead letter queue configuration.
        """
        return DeadLetterConfig(
            enabled=self.ENABLED,
            poll_interval_ms=self.POLL_INTERVAL_MS,
            initial_poll_interval_ms=self.INITIAL_POLL_INTERVAL_MS,
            max_poll_interval_ms=self.MAX_POLL_INTERVAL_MS,
            batch_size=self.BATCH_SIZE,
            concurrent_workers=self.CONCURRENT_WORKERS,
            max_retries=self.MAX_RETRIES,
            retry_backoff_multiplier=float(self.RETRY_BACKOFF_MULTIPLIER),
            retry_max_interval_ms=self.RETRY_MAX_INTERVAL_MS,
            use_skip_locked=self.USE_SKIP_LOCKED,
            archive_after_days=self.ARCHIVE_AFTER_DAYS,
            auto_archive_enabled=self.AUTO_ARCHIVE_ENABLED,
            enable_metrics=self.ENABLE_METRICS,
            handler_retry_enabled=self.HANDLER_RETRY_ENABLED,
            handler_max_retries=self.HANDLER_MAX_RETRIES,
        )


def build_dlq_config(settings: DlqSettings | None = None) -> DeadLetterConfig:
    """Build the internal :class:`DeadLetterConfig` from settings.

    Args:
        settings: Optional settings instance. When omitted, a fresh
            :class:`DlqSettings` is read from the environment.

    Returns:
        The dead letter queue configuration.
    """
    return (settings or DlqSettings()).get_config()
