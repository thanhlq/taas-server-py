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
from typing import Protocol, runtime_checkable

import msgspec

from platform_core.serialization import BaseEntity


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
    """Policy for the DLQ."""

    # Max messages returned per `list_messages` call.
    page_size: int = 100


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
    "IDeadLetterReplayer",
    "IDeadLetterRepository",
]
