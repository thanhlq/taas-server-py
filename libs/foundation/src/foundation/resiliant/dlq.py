"""
Dead Letter Queue (DLQ) primitive.

A DLQ stores messages that could not be processed after exhausting their
retry/recovery budget so they can be inspected, replayed, or purged.

Layout:

* `DeadLetterMessage`     - persisted envelope for a poison message
* `DeadLetterConfig`      - policy (max retention)
* `IDeadLetterRepository` - pluggable storage protocol
* `IDeadLetterReplayer`   - optional sink used by `replay`
* `DeadLetterQueueService`- enqueue / list / replay / purge
* `DeadLetterQueueFactory`- DI helper
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence
from enum import StrEnum
from typing import Any, Dict, Protocol, runtime_checkable

import msgspec

from foundation.serialization import BaseEntity

# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class DeadLetterError(Exception):
    """Base class for DLQ errors."""


class DeadLetterReplayError(DeadLetterError):
    """Raised when replaying a message back to its sink fails."""


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #


class DLQStatus(StrEnum):
    """
    Status of a DLQ event.

    The status represents the current state of a failed event in the DLQ lifecycle.

    Attributes:
        PENDING: Event is waiting to be retried (initial state)
        PROCESSING: Event is currently being retried by a worker
        RESOLVED: Event was successfully reprocessed
        FAILED: Retry attempt failed (will retry again if within max_retries)
        ABANDONED: Max retries exceeded, event cannot be retried automatically
        ARCHIVED: Event has been moved to archive table

    State Transitions:
        PENDING → PROCESSING → RESOLVED (success)
                ↓          ↓
                ↓          → FAILED (retry failed, will retry again)
                ↓          ↓
                → ABANDONED (max retries exceeded)
                  ↓
                  → ARCHIVED (cleanup)

    Example:
        >>> status = DLQStatus.PENDING
        >>> status.value
        'pending'
        >>> status == DLQStatus.PENDING
        True
    """

    PENDING = 'pending'
    """Event is waiting to be retried."""

    APPROVED = 'approved'
    """When admin fixed and approved the event."""

    CANCELLED = 'cancelled'
    """When admin does not want to retry the event."""

    PROCESSING = 'processing'
    """Event is currently being retried by a worker."""

    RESOLVED = 'resolved'
    """Event was successfully reprocessed."""

    FAILED = 'failed'
    """Retry attempt failed (will retry again if within max_retries)."""

    ABANDONED = 'abandoned'
    """Max retries exceeded, event cannot be retried automatically."""

    ARCHIVED = 'archived'
    """Event has been moved to archive table."""

class DeadLetterMessage(BaseEntity):
    """A poison message persisted in the DLQ."""

    id: str
    source: str           # logical origin (topic, queue, handler name)
    payload: bytes
    headers: dict[str, str]
    error: str
    attempts: int
    enqueued_at: float
    original_message_id: str | None = None


class DeadLetterConfig(msgspec.Struct, frozen=True):
    """
    Configuration for DLQ (Dead Letter Queue) retry pattern.

    This configuration controls all aspects of DLQ behavior including
    polling intervals, retry limits, archiving, and metrics.

    Attributes:
        enabled: Enable/disable DLQ functionality
        poll_interval_ms: Base polling interval in milliseconds
        initial_poll_interval_ms: Initial interval for adaptive polling
        max_poll_interval_ms: Maximum interval for adaptive polling
        batch_size: Number of events to fetch per poll
        concurrent_workers: Number of concurrent retry workers
        max_retries: Default maximum retry attempts per event
        retry_backoff_multiplier: Multiplier for exponential backoff
        retry_max_interval_ms: Maximum interval between retries
        use_skip_locked: Use FOR UPDATE SKIP LOCKED for concurrent safety
        archive_after_days: Archive events older than N days
        auto_archive_enabled: Enable automatic archiving
        enable_metrics: Enable metrics collection
        handler_retry_enabled: Enable handler-specific retry logic
        handler_max_retries: Per-handler retry limits

    Example:
        >>> config = DLQConfig(
        ...     enabled=True,
        ...     batch_size=50,
        ...     max_retries=3,
        ...     archive_after_days=30,
        ... )
        >>> dlq_service = DLQService(config)

    Note:
        For production, tune poll_interval_ms and batch_size based on
        your event volume and processing latency requirements.
    """

    # Enable/disable DLQ
    enabled: bool = True
    """Enable or disable DLQ functionality globally."""

    # Polling configuration
    poll_interval_ms: int = 5000
    """Base polling interval in milliseconds (5 seconds default)."""

    initial_poll_interval_ms: int = 1000
    """Initial interval for adaptive polling (1 second default)."""

    max_poll_interval_ms: int = 30000
    """Maximum interval for adaptive polling (30 seconds default)."""

    batch_size: int = 50
    """Number of events to fetch and process per poll."""

    page_size: int = 100
    """Default page size for listing/paginating DLQ messages (``list``)."""

    concurrent_workers: int = 2
    """Number of concurrent retry workers (2 default for safety)."""

    # Retry configuration
    max_retries: int = 3
    """Default maximum retry attempts per event."""

    retry_backoff_multiplier: float = 2.0
    """Multiplier for exponential backoff (2x each retry)."""

    retry_max_interval_ms: int = 60000
    """Maximum interval between retries (60 seconds default)."""

    # Database configuration
    use_skip_locked: bool = True
    """
    Use FOR UPDATE SKIP LOCKED for concurrent safety.

    When True, concurrent workers will skip locked rows instead of waiting,
    preventing deadlocks and improving throughput.
    """

    # Archive configuration
    archive_after_days: int = 30
    """Archive events older than this many days."""

    auto_archive_enabled: bool = True
    """Enable automatic archiving of old events."""

    # Metrics configuration
    enable_metrics: bool = True
    """Enable metrics collection and reporting."""

    # Handler-specific retry configuration
    handler_retry_enabled: bool = True
    """Enable handler-specific retry logic."""

    handler_max_retries: Dict[str, int] = {}
    """
    Per-handler maximum retry limits.

    Example:
        >>> config.handler_max_retries = {
        ...     'OrderHandler': 5,  # More retries for critical handlers
        ...     'NotificationHandler': 2,  # Fewer for non-critical
        ... }
    """


# --------------------------------------------------------------------------- #
# Protocols
# --------------------------------------------------------------------------- #


@runtime_checkable
class IDeadLetterRepository(Protocol):
    """Storage contract for DLQ messages."""

    async def enqueue(self, message: DeadLetterMessage) -> None: ...

    async def get(self, message_id: str) -> DeadLetterMessage | None: ...

    async def list_messages(
        self, *, source: str | None = None, limit: int = 100
    ) -> Sequence[DeadLetterMessage]: ...

    async def delete(self, message_id: str) -> None: ...


@runtime_checkable
class IDeadLetterReplayer(Protocol):
    """Sink used to replay a DLQ message back into the system."""

    async def replay(self, message: DeadLetterMessage) -> None: ...


@runtime_checkable
class IDLQService(Protocol):
    """
    Application-facing contract for the *database-backed* dead letter queue.

    Distinct from :class:`DeadLetterQueueService` (the in-memory primitive
    below), this describes the production service that persists poison messages
    to a relational store so operators can inspect, retry, or abandon them.

    Implementations live in the ``resiliant`` library and are wired through
    ``ResiliantFactory``. Session/return types are left loose (``Any``) so this
    definitions module stays free of persistence-layer imports.
    """

    async def save_event(
        self,
        session: Any,
        *,
        event_id: str,
        event_type: str,
        handler_name: str,
        payload: dict[str, Any],
        error: str,
        source_destination: str | None = None,
        headers: dict[str, Any] | None = None,
        max_retries: int | None = None,
        correlation_id: str | None = None,
    ) -> Any:
        """Persist a failed event to the DLQ."""
        ...

    async def get(self, session: Any, dlq_id: Any) -> Any:
        """Return a single DLQ record by id (or ``None``)."""
        ...

    async def list_pending(self, session: Any, *, limit: int | None = None) -> Any:
        """Return pending DLQ records awaiting retry."""
        ...

    async def get_stats(self, session: Any) -> dict[str, Any]:
        """Return counters describing the current DLQ backlog."""
        ...


# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #


class DeadLetterQueueService:
    """High-level operations on a dead letter queue."""

    def __init__(
        self,
        repository: IDeadLetterRepository,
        config: DeadLetterConfig | None = None,
        *,
        replayer: IDeadLetterReplayer | None = None,
    ) -> None:
        self._repository = repository
        self._config = config or DeadLetterConfig()
        self._replayer = replayer

    async def enqueue(
        self,
        *,
        source: str,
        payload: bytes,
        error: str,
        attempts: int,
        headers: dict[str, str] | None = None,
        original_message_id: str | None = None,
    ) -> DeadLetterMessage:
        message = DeadLetterMessage(
            id=str(uuid.uuid4()),
            source=source,
            payload=payload,
            headers=headers or {},
            error=error,
            attempts=attempts,
            enqueued_at=time.time(),
            original_message_id=original_message_id,
        )
        await self._repository.enqueue(message)
        return message

    async def list(
        self, *, source: str | None = None, limit: int | None = None
    ) -> Sequence[DeadLetterMessage]:
        return await self._repository.list_messages(
            source=source, limit=limit or self._config.page_size
        )

    async def get(self, message_id: str) -> DeadLetterMessage | None:
        return await self._repository.get(message_id)

    async def replay(self, message_id: str, *, delete_on_success: bool = True) -> None:
        if self._replayer is None:
            raise DeadLetterError("No replayer configured for this DLQ service")
        message = await self._repository.get(message_id)
        if message is None:
            raise DeadLetterError(f"DLQ message {message_id!r} not found")
        try:
            await self._replayer.replay(message)
        except BaseException as exc:
            raise DeadLetterReplayError(
                f"Replay of {message_id!r} failed: {exc!r}"
            ) from exc
        if delete_on_success:
            await self._repository.delete(message_id)

    async def purge(self, message_id: str) -> None:
        await self._repository.delete(message_id)


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #


class DeadLetterQueueFactory:
    """Builds `DeadLetterQueueService` instances."""

    def __init__(
        self,
        repository: IDeadLetterRepository,
        config: DeadLetterConfig | None = None,
        *,
        replayer: IDeadLetterReplayer | None = None,
    ) -> None:
        self._repository = repository
        self._config = config
        self._replayer = replayer

    def create_service(
        self,
        config: DeadLetterConfig | None = None,
        *,
        replayer: IDeadLetterReplayer | None = None,
    ) -> DeadLetterQueueService:
        return DeadLetterQueueService(
            repository=self._repository,
            config=config or self._config,
            replayer=replayer or self._replayer,
        )


__all__ = [
    "DeadLetterConfig",
    "DeadLetterError",
    "DeadLetterMessage",
    "DeadLetterQueueFactory",
    "DeadLetterQueueService",
    "DeadLetterReplayError",
    "DLQStatus",
    "IDeadLetterReplayer",
    "IDeadLetterRepository",
    "IDLQService",
]
