"""Outbox settings from the environment — the same ``OUTBOX_*`` variables and defaults as
``ResiliantSettings`` of ``@taas/foundation`` (taas-server-js), so one ``.env`` drives both relays.

A malformed value raises (``get_env`` conversion / ``OutboxConfig`` validation); it never
silently falls back to a default.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import cast

from foundation.resiliant.outbox import OutboxConfig, PollStrategy, RoutingStrategy
from foundation.utils.env_utils import get_env

_D = OutboxConfig()


@dataclass
class OutboxSettings:
    """Transactional outbox configuration (``OUTBOX_*``), mapped onto :class:`OutboxConfig`."""

    ENABLED: bool = field(default_factory=get_env('OUTBOX_ENABLED', True))
    POLL_OUTBOXES: str = field(default_factory=get_env('OUTBOX_POLL_OUTBOXES', ''))
    """Comma-separated outboxes the worker relays (``messaging,transaction``); empty = all registered."""

    POLL_STRATEGY: str = field(
        default_factory=get_env('OUTBOX_POLL_STRATEGY', _D.poll_strategy)
    )
    FIXED_POLL_INTERVAL_MS: int = field(
        default_factory=get_env(
            'OUTBOX_FIXED_POLL_INTERVAL_MS', _D.fixed_poll_interval_ms
        )
    )
    MIN_POLL_INTERVAL_MS: int = field(
        default_factory=get_env('OUTBOX_MIN_POLL_INTERVAL_MS', _D.min_poll_interval_ms)
    )
    MAX_POLL_INTERVAL_MS: int = field(
        default_factory=get_env('OUTBOX_MAX_POLL_INTERVAL_MS', _D.max_poll_interval_ms)
    )
    INITIAL_POLL_INTERVAL_MS: int = field(
        default_factory=get_env(
            'OUTBOX_INITIAL_POLL_INTERVAL_MS', _D.initial_poll_interval_ms
        )
    )
    BACKOFF_GROWTH_FACTOR: float = field(
        default_factory=get_env(
            'OUTBOX_BACKOFF_GROWTH_FACTOR', _D.backoff_growth_factor
        )
    )
    DRAIN_THRESHOLD_RATIO: float = field(
        default_factory=get_env(
            'OUTBOX_DRAIN_THRESHOLD_RATIO', _D.drain_threshold_ratio
        )
    )
    NOTIFY_CHANNEL: str = field(
        default_factory=get_env('OUTBOX_NOTIFY_CHANNEL', _D.notify_channel)
    )
    NOTIFY_DSN: str = field(default_factory=get_env('OUTBOX_NOTIFY_DSN', ''))
    """LISTEN connection (Python only); empty = derived from ``DATABASE_URL``."""

    BATCH_SIZE: int = field(default_factory=get_env('OUTBOX_BATCH_SIZE', _D.batch_size))
    CONCURRENT_WORKERS: int = field(
        default_factory=get_env('OUTBOX_CONCURRENT_WORKERS', _D.concurrent_workers)
    )
    MAX_RETRIES: int = field(
        default_factory=get_env('OUTBOX_MAX_RETRIES', _D.max_retries)
    )
    RETRY_BACKOFF_MULTIPLIER: float = field(
        default_factory=get_env(
            'OUTBOX_RETRY_BACKOFF_MULTIPLIER', _D.retry_backoff_multiplier
        )
    )
    RETRY_MAX_BACKOFF_MS: int = field(
        default_factory=get_env('OUTBOX_RETRY_MAX_BACKOFF_MS', _D.retry_max_backoff_ms)
    )
    DISPATCH_TIMEOUT_MS: int = field(
        default_factory=get_env('OUTBOX_DISPATCH_TIMEOUT_MS', _D.dispatch_timeout_ms)
    )
    PRESERVE_ORDERING: bool = field(
        default_factory=get_env('OUTBOX_PRESERVE_ORDERING', _D.preserve_ordering)
    )
    BREAKER_FAILURE_THRESHOLD: int = field(
        default_factory=get_env(
            'OUTBOX_BREAKER_FAILURE_THRESHOLD', _D.breaker_failure_threshold
        )
    )
    BREAKER_COOLDOWN_MS: int = field(
        default_factory=get_env('OUTBOX_BREAKER_COOLDOWN_MS', _D.breaker_cooldown_ms)
    )
    RETENTION_DAYS: int = field(
        default_factory=get_env('OUTBOX_RETENTION_DAYS', _D.retention_days)
    )
    ENABLE_METRICS: bool = field(
        default_factory=get_env('OUTBOX_ENABLE_METRICS', _D.enable_metrics)
    )
    METRICS_LOG_INTERVAL_MS: int = field(
        default_factory=get_env(
            'OUTBOX_METRICS_LOG_INTERVAL_MS', _D.metrics_log_interval_ms
        )
    )

    # Messaging routing (Python MessageRoutingService)
    DEFAULT_ROUTING: str = field(
        default_factory=get_env('OUTBOX_DEFAULT_ROUTING', 'outbox')
    )
    DIRECT_CHANNELS: str = field(
        default_factory=get_env('OUTBOX_DIRECT_CHANNEL_ROUTING', '')
    )
    """Channels published directly (no outbox), e.g. ``audits,notifications``."""
    OUTBOX_CHANNEL: str = field(default_factory=get_env('OUTBOX_OUTBOX_CHANNEL', ''))

    def get_config(self) -> OutboxConfig:
        """The validated :class:`OutboxConfig`."""
        direct = {
            c.strip(): c.strip() for c in self.DIRECT_CHANNELS.split(',') if c.strip()
        }
        outbox = (
            {self.OUTBOX_CHANNEL: self.OUTBOX_CHANNEL} if self.OUTBOX_CHANNEL else {}
        )
        return OutboxConfig(
            enabled=self.ENABLED,
            poll_strategy=cast(PollStrategy, self.POLL_STRATEGY),
            fixed_poll_interval_ms=int(self.FIXED_POLL_INTERVAL_MS),
            min_poll_interval_ms=int(self.MIN_POLL_INTERVAL_MS),
            max_poll_interval_ms=int(self.MAX_POLL_INTERVAL_MS),
            initial_poll_interval_ms=int(self.INITIAL_POLL_INTERVAL_MS),
            backoff_growth_factor=float(self.BACKOFF_GROWTH_FACTOR),
            drain_threshold_ratio=float(self.DRAIN_THRESHOLD_RATIO),
            notify_channel=self.NOTIFY_CHANNEL,
            notify_dsn=self.NOTIFY_DSN or None,
            batch_size=int(self.BATCH_SIZE),
            concurrent_workers=int(self.CONCURRENT_WORKERS),
            max_retries=int(self.MAX_RETRIES),
            retry_backoff_multiplier=float(self.RETRY_BACKOFF_MULTIPLIER),
            retry_max_backoff_ms=int(self.RETRY_MAX_BACKOFF_MS),
            dispatch_timeout_ms=int(self.DISPATCH_TIMEOUT_MS),
            preserve_ordering=bool(self.PRESERVE_ORDERING),
            breaker_failure_threshold=int(self.BREAKER_FAILURE_THRESHOLD),
            breaker_cooldown_ms=int(self.BREAKER_COOLDOWN_MS),
            retention_days=int(self.RETENTION_DAYS),
            enable_metrics=bool(self.ENABLE_METRICS),
            metrics_log_interval_ms=int(self.METRICS_LOG_INTERVAL_MS),
            routing_default=cast(RoutingStrategy, self.DEFAULT_ROUTING),
            direct_channels=direct,
            outbox_channels=outbox,
        )


@lru_cache(maxsize=1)
def get_outbox_config(settings: OutboxSettings | None = None) -> OutboxConfig:
    """The validated :class:`OutboxConfig` from ``settings`` (default: the environment)."""
    return (settings or OutboxSettings()).get_config()


def get_polled_outboxes(settings: OutboxSettings | None = None) -> list[str] | None:
    """Outbox names from ``OUTBOX_POLL_OUTBOXES``; ``None`` = all registered outboxes."""
    raw = (settings or OutboxSettings()).POLL_OUTBOXES
    names = [name.strip() for name in raw.split(',') if name.strip()]
    return names or None
