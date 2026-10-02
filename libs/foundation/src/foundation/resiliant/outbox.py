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
import re
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
    """Same values as ``outboxStatuses`` of ``@taas/foundation/resiliant`` (shared tables).

    There is no ``processing`` state: the relay claims rows with row locks held by its
    transaction (``FOR UPDATE SKIP LOCKED``) and writes the outcome before committing.
    """

    PENDING = 'pending'
    PUBLISHED = 'published'
    FAILED = 'failed'
    DEAD_LETTER = 'dead_letter'


CLAIMABLE_OUTBOX_STATUSES: tuple[OutboxStatus, ...] = (OutboxStatus.PENDING, OutboxStatus.FAILED)
"""Statuses the relay claims (the ``*_due_idx`` partial index predicate)."""


class OutboxTarget(enum.StrEnum):
    """Where the relay delivers an outbox record (one dispatcher per target).

    Stored on every record, so one outbox table can feed several targets; the
    poller routes each record to the dispatcher registered for its target.
    """

    MESSAGING = 'messaging'
    """Publish to the message broker (Kafka, …) via ``MessagingServiceT``."""


class OutboxName(enum.StrEnum):
    """Built-in outboxes — one table per use case (see ``resiliant.outbox.registry``).

    Plain strings are accepted wherever an outbox name is expected, so apps can
    register their own outboxes without extending this enum.
    """

    MESSAGING = 'messaging'
    """Domain events published to the broker (``resiliant_outbox_messages``)."""

    TRANSACTION = 'transaction'
    """Inbound transaction requests relayed to a target (``resiliant_outbox_transactions``)."""


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
    """Outbox relay policy — same fields, defaults and checks as ``OutboxConfigT``
    (``@taas/foundation/resiliant``), read from the same ``OUTBOX_*`` variables
    (``resiliant.outbox.outbox_settings``).
    """

    enabled: bool = True
    poll_strategy: PollStrategy = 'adaptive'
    """``fixed`` (constant sleep), ``adaptive`` (decorrelated jitter), ``notify`` (adaptive + LISTEN wake-up)."""
    fixed_poll_interval_ms: int = 1000
    min_poll_interval_ms: int = 50
    max_poll_interval_ms: int = 2000
    initial_poll_interval_ms: int = 200
    backoff_growth_factor: float = 3.0
    """Idle sleep = U(min, min(max, previous × factor)); must be > 1."""
    drain_threshold_ratio: float = 1.0
    """A poll that claimed >= batch_size × ratio records polls again without sleeping."""
    notify_channel: str = 'resiliant_outbox'
    """``LISTEN`` channel of the ``notify`` strategy; writers ``NOTIFY`` it on commit."""
    notify_dsn: Optional[str] = None
    """Connection string of the dedicated LISTEN connection (Python only); default = the app database."""
    batch_size: int = 100
    concurrent_workers: int = 1
    """Parallel relay loops in one process (rows are split by SKIP LOCKED)."""
    max_retries: int = 10
    retry_backoff_multiplier: float = 2.0
    """Retry n waits multiplier^n seconds, capped by ``retry_max_backoff_ms``."""
    retry_max_backoff_ms: int = 300_000
    dispatch_timeout_ms: int = 30_000
    """A dispatch slower than this is a failure (the record may still have been delivered)."""
    preserve_ordering: bool = True
    """Records sharing an ordering key (per target + channel) are delivered in id order."""
    breaker_failure_threshold: int = 3
    """Distinct records failing in a row that mean "the target is down"."""
    breaker_cooldown_ms: int = 5000
    retention_days: int = 7
    """Published records older than this are purged by maintenance."""
    enable_metrics: bool = True
    metrics_log_interval_ms: int = 60_000

    # Messaging routing (Python ``MessageRoutingService``): outbox vs direct publish per channel.
    routing_default: RoutingStrategy = 'outbox'
    direct_channels: dict[str, str] = {}
    outbox_channels: dict[str, str] = {}

    def __post_init__(self) -> None:
        """Validate like ``resolveOutboxConfig``: a policy that cannot work raises."""
        if self.poll_strategy not in ('fixed', 'adaptive', 'notify'):
            raise ValueError(f'outbox poll_strategy must be fixed, adaptive or notify, got {self.poll_strategy!r}')
        if self.min_poll_interval_ms > self.max_poll_interval_ms:
            raise ValueError(
                f'outbox min_poll_interval_ms ({self.min_poll_interval_ms}) > max_poll_interval_ms ({self.max_poll_interval_ms})'
            )
        msgspec.structs.force_setattr(
            self,
            'initial_poll_interval_ms',
            min(max(self.initial_poll_interval_ms, self.min_poll_interval_ms), self.max_poll_interval_ms),
        )
        for name, minimum in (
            ('fixed_poll_interval_ms', 1),
            ('min_poll_interval_ms', 0),
            ('batch_size', 1),
            ('concurrent_workers', 1),
            ('max_retries', 1),
            ('retry_backoff_multiplier', 1),
            ('retry_max_backoff_ms', 0),
            ('dispatch_timeout_ms', 1),
            ('breaker_failure_threshold', 1),
            ('breaker_cooldown_ms', 0),
            ('retention_days', 1),
            ('drain_threshold_ratio', 0),
        ):
            if getattr(self, name) < minimum:
                raise ValueError(f'outbox {name} must be >= {minimum}, got {getattr(self, name)}')
        if not self.backoff_growth_factor > 1:
            raise ValueError(f'outbox backoff_growth_factor must be > 1, got {self.backoff_growth_factor}')
        if not re.fullmatch(r'[a-z_][a-z0-9_]{0,62}', self.notify_channel):
            raise ValueError(f'outbox notify_channel must be a plain lower-case identifier, got {self.notify_channel!r}')


class OutboxBatchResult(msgspec.Struct, frozen=True):
    """Outcome of one relay step (``OutboxBatchResultT``)."""

    claimed: int = 0
    published: int = 0
    failed: int = 0
    dead_lettered: int = 0
    deferred: int = 0
    circuit: str = 'closed'
    """``closed`` | ``open`` | ``half_open`` — the relay's view of its target."""


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
class IOutboxRecord(Protocol):
    """Columns every outbox table provides — what the generic relay relies on.

    Use-case tables add their own columns on top (``resiliant.models.outbox``).
    """

    id: int
    event_type: str
    target: OutboxTarget | str
    channel: str | None
    ordering_key: str | None
    payload: dict[str, Any]
    headers: dict[str, Any] | None
    status: OutboxStatus
    retry_count: int
    max_retries: int
    last_error: str | None
    correlation_id: str | None


@runtime_checkable
class IOutboxDispatcher(Protocol):
    """Delivers claimed outbox records to one :class:`OutboxTarget`.

    Raising marks the record failed (retried with capped backoff until
    ``max_retries``, then ``dead_letter`` — unless the relay attributes the failure to
    the target being down); returning marks it published.
    """

    target: OutboxTarget

    async def dispatch(self, record: IOutboxRecord) -> None: ...


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

    This is the *messaging* outbox contract (domain events → broker). Get it via
    ``ResiliantServiceFactoryT.get_messaging_outbox_service()``; other use cases
    have their own contracts (e.g. :class:`ITransactionOutboxService`). Session/event/return types are intentionally left
    loose (``Any``) so this definitions module stays free of SQLAlchemy and
    persistence-layer imports.
    """

    async def save_event(
        self,
        session: Any,
        event: Any,
        channel: str,
        *,
        ordering_key: str | None = None,
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
        ordering_key: str | None = None,
        headers: dict[str, Any] | None = None,
        max_retries: int | None = None,
    ) -> Any:
        """Persist a raw (already-serialised) message to the outbox."""
        ...

    async def get_stats(self, session: Any) -> dict[str, Any]:
        """Return counters describing the current outbox backlog."""
        ...


@runtime_checkable
class ITransactionOutboxService(Protocol):
    """Records inbound transaction requests for reliable relay to a target.

    ``request_id`` is the caller's idempotency key: saving the same request twice
    returns the existing record instead of enqueuing a duplicate. Obtain it via
    ``ResiliantServiceFactoryT.get_transaction_outbox_service(target=…)``.
    """

    async def save_transaction(
        self,
        session: Any,
        *,
        request_id: str,
        transaction_type: str,
        payload: dict[str, Any],
        channel: str | None = None,
        ordering_key: str | None = None,
        account_ref: str | None = None,
        source_system: str | None = None,
        headers: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        max_retries: int | None = None,
    ) -> Any:
        """Persist a transaction request within ``session`` (idempotent on ``request_id``)."""
        ...

    async def get_stats(self, session: Any) -> dict[str, Any]:
        """Return counters describing the current outbox backlog."""
        ...







__all__ = [
    "IOutboxDispatcher",
    "IOutboxPublisher",
    "IOutboxRecord",
    "IOutboxRepository",
    "IOutboxService",
    "ITransactionOutboxService",
    "OutboxConfig",
    "OutboxError",
    "OutboxMessage",
    "OutboxName",
    "OutboxPublishError",
    "OutboxStatus",
    "OutboxTarget",
]
