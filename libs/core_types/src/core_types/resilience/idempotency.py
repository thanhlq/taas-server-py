"""
Idempotency primitives.

The idempotency pattern guarantees that retried or duplicated requests that
share the same idempotency key produce the same observable result and the
underlying side-effect runs at most once.

Layout:

* `IdempotencyStatus`      - lifecycle state of a record
* `IdempotencyRecord`      - persisted state for a single key
* `IdempotencyConfig`      - policy (namespace, TTLs)
* `IIdempotencyRepository` - storage protocol (pluggable backend)
* `IdempotencyService`     - orchestrates reserve -> execute -> complete
* `IdempotencyFactory`     - DI helper to build a service from a repository
* Exceptions               - `IdempotencyConflictError`, `IdempotencyInProgressError`
"""

from __future__ import annotations

import enum
import hashlib
import time
from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

import msgspec

from core_types.base_entity import BaseEntity


# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class IdempotencyError(Exception):
    """Base class for idempotency errors."""


class IdempotencyInProgressError(IdempotencyError):
    """Raised when a concurrent request for the same key is still running."""

    def __init__(self, key: str) -> None:
        super().__init__(f"Request for idempotency key {key!r} is in progress")
        self.key = key


class IdempotencyConflictError(IdempotencyError):
    """Raised when the same key is reused with a different request payload."""

    def __init__(self, key: str) -> None:
        super().__init__(
            f"Idempotency key {key!r} was reused with a different request payload"
        )
        self.key = key


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #


class IdempotencyStatus(enum.StrEnum):
    """Lifecycle state of an idempotency record."""

    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class IdempotencyRecord(BaseEntity):
    """
    Persisted state associated with a single idempotency key.

    `response` is opaque bytes so the storage layer stays serializer-agnostic.
    `fingerprint` is an optional digest of the request payload used to detect
    accidental key reuse with a different payload.
    """

    key: str
    status: IdempotencyStatus
    created_at: float
    completed_at: float | None = None
    fingerprint: str | None = None
    response: bytes | None = None


class IdempotencyConfig(msgspec.Struct, frozen=True):
    """Policy for the idempotency service."""

    # Logical bucket; backends typically use it as a key prefix.
    namespace: str = "default"
    # How long a completed response is retained.
    ttl_seconds: int = 24 * 60 * 60
    # How long a reservation may stay IN_PROGRESS before being considered stale.
    in_progress_ttl_seconds: int = 60


# --------------------------------------------------------------------------- #
# Repository protocol
# --------------------------------------------------------------------------- #


@runtime_checkable
class IIdempotencyRepository(Protocol):
    """
    Storage contract for idempotency records.

    Implementations must make `reserve` atomic: only the first caller for a
    given key may succeed; concurrent callers must observe the existing
    record.
    """

    async def reserve(
        self,
        namespace: str,
        record: IdempotencyRecord,
        *,
        ttl_seconds: int,
    ) -> IdempotencyRecord:
        """
        Atomically create a record in `IN_PROGRESS` state.

        Returns the input `record` on success. On conflict, returns the
        already-stored record (which may be `IN_PROGRESS`, `COMPLETED`, or
        `FAILED`).
        """
        ...

    async def get(self, namespace: str, key: str) -> IdempotencyRecord | None:
        """Return the record for `key` or `None` if not stored."""
        ...

    async def complete(
        self,
        namespace: str,
        key: str,
        *,
        response: bytes,
        completed_at: float,
        ttl_seconds: int,
    ) -> None:
        """Mark a reserved record as `COMPLETED` and persist its response."""
        ...

    async def fail(self, namespace: str, key: str) -> None:
        """Release a reserved record so the caller may retry."""
        ...


# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #


_default_encoder = msgspec.json.Encoder()


def _fingerprint(payload: bytes | None) -> str | None:
    if payload is None:
        return None
    return hashlib.sha256(payload).hexdigest()


class IdempotencyService:
    """
    Orchestrates the idempotency lifecycle around a handler.

    Typical usage::

        response = await service.execute(
            key="order-123",
            handler=create_order,
            request_payload=raw_body,
        )

    Semantics:

    * Fresh key: the handler runs, its result is stored, and returned.
    * Duplicate completed key: the cached response is returned.
    * Concurrent in-progress key: `IdempotencyInProgressError` is raised.
    * Key reused with a different `request_payload` (fingerprint mismatch):
      `IdempotencyConflictError` is raised.
    """

    def __init__(
        self,
        repository: IIdempotencyRepository,
        config: IdempotencyConfig | None = None,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._repository = repository
        self._config = config or IdempotencyConfig()
        self._clock = clock

    @property
    def config(self) -> IdempotencyConfig:
        return self._config

    async def execute(
        self,
        key: str,
        handler: Callable[[], Awaitable[bytes]],
        *,
        request_payload: bytes | None = None,
    ) -> bytes:
        """Run `handler` at most once for `key` and return its response bytes."""
        cfg = self._config
        fingerprint = _fingerprint(request_payload)
        now = self._clock()

        reservation = IdempotencyRecord(
            key=key,
            status=IdempotencyStatus.IN_PROGRESS,
            created_at=now,
            fingerprint=fingerprint,
        )

        stored = await self._repository.reserve(
            cfg.namespace, reservation, ttl_seconds=cfg.in_progress_ttl_seconds
        )

        if stored is not reservation:
            return self._resolve_existing(stored, fingerprint)

        try:
            response = await handler()
        except BaseException:
            await self._repository.fail(cfg.namespace, key)
            raise

        await self._repository.complete(
            cfg.namespace,
            key,
            response=response,
            completed_at=self._clock(),
            ttl_seconds=cfg.ttl_seconds,
        )
        return response

    async def execute_typed[T: msgspec.Struct](
        self,
        key: str,
        handler: Callable[[], Awaitable[T]],
        response_type: type[T],
        *,
        request_payload: bytes | None = None,
    ) -> T:
        """Typed convenience wrapper that JSON-encodes/decodes the response."""

        async def _runner() -> bytes:
            return _default_encoder.encode(await handler())

        raw = await self.execute(key, _runner, request_payload=request_payload)
        return msgspec.json.decode(raw, type=response_type)

    async def get(self, key: str) -> IdempotencyRecord | None:
        """Return the stored record for `key`, if any."""
        return await self._repository.get(self._config.namespace, key)

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _resolve_existing(
        self, record: IdempotencyRecord, fingerprint: str | None
    ) -> bytes:
        if (
            fingerprint is not None
            and record.fingerprint is not None
            and fingerprint != record.fingerprint
        ):
            raise IdempotencyConflictError(record.key)

        match record.status:
            case IdempotencyStatus.COMPLETED:
                if record.response is None:
                    raise IdempotencyError(
                        f"Completed record for {record.key!r} has no response"
                    )
                return record.response
            case IdempotencyStatus.IN_PROGRESS:
                raise IdempotencyInProgressError(record.key)
            case IdempotencyStatus.FAILED:
                raise IdempotencyError(
                    f"Previous attempt for {record.key!r} failed; retry with a new key"
                )


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #


class IdempotencyFactory:
    """Builds `IdempotencyService` instances bound to a single repository."""

    def __init__(
        self,
        repository: IIdempotencyRepository,
        config: IdempotencyConfig | None = None,
    ) -> None:
        self._repository = repository
        self._config = config

    def create_service(
        self, config: IdempotencyConfig | None = None
    ) -> IdempotencyService:
        return IdempotencyService(
            repository=self._repository,
            config=config or self._config,
        )


__all__ = [
    "IIdempotencyRepository",
    "IdempotencyConfig",
    "IdempotencyConflictError",
    "IdempotencyError",
    "IdempotencyFactory",
    "IdempotencyInProgressError",
    "IdempotencyRecord",
    "IdempotencyService",
    "IdempotencyStatus",
]
