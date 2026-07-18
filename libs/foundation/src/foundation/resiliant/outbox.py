"""
Transactional Outbox primitive.

The outbox pattern atomically records messages alongside business state
changes so they can be reliably published later by a relay process, even if
the message broker is temporarily unavailable.

Layout:

* `OutboxStatus`        - lifecycle state of a message
* `OutboxMessage`       - persisted message envelope
* `OutboxConfig`        - policy (batch size, retry caps)
* `IOutboxRepository`   - pluggable storage protocol
* `IOutboxPublisher`    - pluggable broker protocol
* `OutboxService`       - enqueue API + relay loop
* `OutboxFactory`       - DI helper
"""

from __future__ import annotations

import enum
from collections.abc import Sequence
from typing import Any, Literal, Optional, Protocol, runtime_checkable

import msgspec

from foundation.serialization import BaseModel

# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class OutboxError(Exception):
    """Base class for outbox errors."""


class OutboxPublishError(OutboxError):
    """Raised when the underlying broker rejects a message permanently."""


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #


class OutboxStatus(enum.StrEnum):
    PENDING = 'pending'
    PROCESSING = 'processing'
    PUBLISHED = 'published'
    FAILED = 'failed'
    DEAD_LETTER = 'dead_letter'


class OutboxMessage(BaseModel):
    """A message awaiting publication."""

    id: str
    topic: str
    payload: bytes
    headers: dict[str, str]
    status: OutboxStatus
    created_at: float
    attempts: int = 0
    last_error: str | None = None
    published_at: float | None = None

PollStrategy = Literal['fixed', 'adaptive', 'notify']
type RoutingStrategy = Literal['outbox', 'direct']

class OutboxConfig(msgspec.Struct, frozen=True):
    """
    Configuration for outbox pattern implementation.

    Attributes:
        enabled: Whether outbox polling is enabled
        min_poll_interval_ms: Minimum polling interval when busy (ms)
        max_poll_interval_ms: Maximum polling interval when idle (ms)
        initial_poll_interval_ms: Starting polling interval (ms)
        batch_size: Number of events to fetch per poll
        concurrent_workers: Number of concurrent poller workers
        max_retries: Maximum retry attempts before moving to DLQ
        retry_backoff_multiplier: Exponential backoff multiplier for retries
        processing_timeout_seconds: Timeout for processing events
        use_skip_locked: Use FOR UPDATE SKIP LOCKED in queries
        use_read_replica: Use read replica for initial queries
        archive_after_days: Move published events to archive after N days
        cleanup_archive_after_days: Delete archived events after N days
        enable_metrics: Enable metrics collection
    """

    enabled: bool = True

    # Poll strategy selection:
    #   'fixed'    - sleep `fixed_poll_interval_ms` every cycle (legacy 1s behavior)
    #   'adaptive' - decorrelated jitter backoff between min/max based on activity
    #   'notify'   - adaptive backoff PLUS Postgres LISTEN/NOTIFY wake-up
    poll_strategy: PollStrategy = 'fixed'

    # Polling configuration
    fixed_poll_interval_ms: int = 3000  # used when poll_strategy == 'fixed'
    min_poll_interval_ms: int = 100
    max_poll_interval_ms: int = 20000  # default 2000 (2 seconds)
    initial_poll_interval_ms: int = 5000  # default 500
    """ Initial polling interval in milliseconds.
    This value should be between min_poll_interval_ms and max_poll_interval_ms."""

    # Adaptive backoff tuning (decorrelated jitter: next = U(min, prev * growth))
    backoff_growth_factor: float = 3.0
    drain_threshold_ratio: float = 1.0
    """When fetched_count >= batch_size * drain_threshold_ratio, skip sleep
    and immediately poll again ('drain mode')."""

    # NOTIFY strategy (Postgres LISTEN/NOTIFY)
    notify_channel: str = 'outbox_new_event'
    notify_dsn: Optional[str] = None
    """Optional asyncpg DSN for the LISTEN connection. If None, only in-process
    `OutboxPoller.wake()` calls will trigger early polling."""

    # Batch processing
    batch_size: int = 100
    concurrent_workers: int = 1  # Number of parallel poller workers ()

    # Retry configuration
    max_retries: int = 3
    retry_backoff_multiplier: float = 2.0
    processing_timeout_seconds: int = 30

    # Database optimizations
    use_skip_locked: bool = True
    use_read_replica: bool = False

    # Archiving configuration
    archive_after_days: int = 7
    cleanup_archive_after_days: int = 30

    # Monitoring
    enable_metrics: bool = True
    metrics_log_interval_seconds: int = 60

    # Connection pool
    db_pool_min_size: int = 5
    db_pool_max_size: int = 20
    db_query_timeout_ms: int = 5000

    # Messaging Routing
    routing_default: RoutingStrategy = 'outbox'
    direct_channels: dict[str, str] = {}
    outbox_channels: dict[str, str] = {}

    def __post_init__(self):
        """Validate configuration."""
        if self.min_poll_interval_ms > self.max_poll_interval_ms:
            raise ValueError(
                f'min_poll_interval_ms ({self.min_poll_interval_ms}) cannot be '
                f'greater than max_poll_interval_ms ({self.max_poll_interval_ms})'
            )

        if self.initial_poll_interval_ms < self.min_poll_interval_ms:
            self.initial_poll_interval_ms = self.min_poll_interval_ms

        if self.initial_poll_interval_ms > self.max_poll_interval_ms:
            self.initial_poll_interval_ms = self.max_poll_interval_ms

        if self.batch_size < 1:
            raise ValueError(f'batch_size must be at least 1, got {self.batch_size}')

        if self.concurrent_workers < 1:
            raise ValueError(
                f'concurrent_workers must be at least 1, got {self.concurrent_workers}'
            )

        if self.poll_strategy not in ('fixed', 'adaptive', 'notify'):
            raise ValueError(
                f"poll_strategy must be one of 'fixed', 'adaptive', 'notify', "
                f"got {self.poll_strategy!r}"
            )

        if self.fixed_poll_interval_ms < 1:
            raise ValueError(
                f'fixed_poll_interval_ms must be >= 1, got {self.fixed_poll_interval_ms}'
            )

        if self.backoff_growth_factor <= 1.0:
            raise ValueError(
                f'backoff_growth_factor must be > 1.0, got {self.backoff_growth_factor}'
            )


# --------------------------------------------------------------------------- #
# Protocols
# --------------------------------------------------------------------------- #


@runtime_checkable
class IOutboxRepository(Protocol):
    """Storage contract for outbox messages."""

    async def enqueue(self, message: OutboxMessage) -> None:
        """Persist a new PENDING message (typically inside the business txn)."""
        ...

    async def fetch_pending(self, *, limit: int) -> Sequence[OutboxMessage]:
        """Return up to `limit` PENDING messages, locked for processing."""
        ...

    async def mark_published(self, message_id: str, *, published_at: float) -> None: ...

    async def mark_failed(
        self, message_id: str, *, attempts: int, error: str, terminal: bool
    ) -> None: ...


@runtime_checkable
class IOutboxPublisher(Protocol):
    """Broker-facing publisher (Kafka, RabbitMQ, SNS, ...)."""

    async def publish(self, message: OutboxMessage) -> None: ...


@runtime_checkable
class IOutboxService(Protocol):
    """
    Application-facing contract for the transactional outbox.

    Unlike :class:`OutboxService` (the in-memory relay primitive above), this
    protocol describes the *database-backed* service used in production: events
    are persisted inside the caller's business transaction (same
    ``AsyncSession``) so the write and the message enqueue commit atomically.

    Implementations live in the ``resiliant`` library and are wired through
    ``ResiliantFactory``. Session/event/return types are intentionally left
    loose (``Any``) so this definitions module stays free of SQLAlchemy and
    persistence-layer imports.
    """

    async def save_event(
        self,
        session: Any,
        event: Any,
        channel: str,
        *,
        partition_key: str | None = None,
        headers: dict[str, Any] | None = None,
        max_retries: int | None = None,
    ) -> Any:
        """Persist a domain event to the outbox within ``session``."""
        ...

    async def save_raw_message(
        self,
        session: Any,
        *,
        channel: str,
        payload: dict[str, Any],
        event_type: str,
        partition_key: str | None = None,
        headers: dict[str, Any] | None = None,
        max_retries: int | None = None,
    ) -> Any:
        """Persist a raw (already-serialised) message to the outbox."""
        ...

    async def get_stats(self, session: Any) -> dict[str, Any]:
        """Return counters describing the current outbox backlog."""
        ...







__all__ = [
    "IOutboxPublisher",
    "IOutboxRepository",
    "IOutboxService",
    "OutboxConfig",
    "OutboxError",
    "OutboxFactory",
    "OutboxMessage",
    "OutboxPublishError",
    "OutboxService",
    "OutboxStatus",
]
