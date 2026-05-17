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
import time
import uuid
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

import msgspec

from core_types.base_entity import BaseEntity


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
    PENDING = "pending"
    PUBLISHED = "published"
    FAILED = "failed"


class OutboxMessage(BaseEntity):
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


class OutboxConfig(msgspec.Struct, frozen=True):
    """Policy for the outbox relay."""

    # Max messages fetched per relay tick.
    batch_size: int = 100
    # Max attempts before a message is moved to FAILED.
    max_attempts: int = 10


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


# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #


class OutboxService:
    """
    Enqueue messages and run a relay tick that drains PENDING into the broker.
    """

    def __init__(
        self,
        repository: IOutboxRepository,
        publisher: IOutboxPublisher,
        config: OutboxConfig | None = None,
    ) -> None:
        self._repository = repository
        self._publisher = publisher
        self._config = config or OutboxConfig()

    async def enqueue(
        self,
        topic: str,
        payload: bytes,
        *,
        headers: dict[str, str] | None = None,
        message_id: str | None = None,
    ) -> OutboxMessage:
        message = OutboxMessage(
            id=message_id or str(uuid.uuid4()),
            topic=topic,
            payload=payload,
            headers=headers or {},
            status=OutboxStatus.PENDING,
            created_at=time.time(),
        )
        await self._repository.enqueue(message)
        return message

    async def relay_once(self) -> int:
        """Process one batch. Returns the number of messages successfully published."""
        cfg = self._config
        pending = await self._repository.fetch_pending(limit=cfg.batch_size)
        published = 0
        for message in pending:
            attempts = message.attempts + 1
            try:
                await self._publisher.publish(message)
            except Exception as exc:  # noqa: BLE001 - boundary
                terminal = attempts >= cfg.max_attempts
                await self._repository.mark_failed(
                    message.id,
                    attempts=attempts,
                    error=repr(exc),
                    terminal=terminal,
                )
                continue
            await self._repository.mark_published(
                message.id, published_at=time.time()
            )
            published += 1
        return published


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #


class OutboxFactory:
    """Builds `OutboxService` instances."""

    def __init__(
        self,
        repository: IOutboxRepository,
        publisher: IOutboxPublisher,
        config: OutboxConfig | None = None,
    ) -> None:
        self._repository = repository
        self._publisher = publisher
        self._config = config

    def create_service(self, config: OutboxConfig | None = None) -> OutboxService:
        return OutboxService(
            repository=self._repository,
            publisher=self._publisher,
            config=config or self._config,
        )


__all__ = [
    "IOutboxPublisher",
    "IOutboxRepository",
    "OutboxConfig",
    "OutboxError",
    "OutboxFactory",
    "OutboxMessage",
    "OutboxPublishError",
    "OutboxService",
    "OutboxStatus",
]
