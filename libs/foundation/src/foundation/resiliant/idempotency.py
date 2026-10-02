"""
Idempotency primitive.

The idempotency pattern guarantees that an at-least-once event delivery
system processes the business side-effect of a given event **at most once**
per handler. Two workers that receive the same message are protected by a
database-level uniqueness constraint (PostgreSQL
``INSERT … ON CONFLICT (idempotency_key) DO NOTHING``): exactly one insert
wins, the rest observe a duplicate.

Layout
------
* ``IdempotencyStatus``   - lifecycle state recorded for a key
* ``IdempotencyBackend``  - where keys are stored (``postgres`` | ``redis``)
* ``DuplicateEventError`` - raised (strict mode) when a duplicate is seen
* ``IdempotencyConfig``   - policy (backend, key format, TTL, cleanup, behaviour flags)
* ``IIdempotencyStore``   - storage contract (one implementation per backend)
* ``IIdempotencyService`` - application-facing contract

Implementations (service, Postgres and Redis stores, settings loader) live in
the ``resiliant`` library (``resiliant.idempotency``), wired through
``ResiliantServiceFactory``; the Postgres table is ``resiliant.models.ProcessedEventTable``.

Session/return types on the service contract are intentionally loose
(``Any``) so this definitions module stays free of any persistence-layer
import — mirroring the ``dlq`` and ``outbox`` definitions in this package.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from enum import StrEnum
from typing import Any, Optional, Protocol, runtime_checkable

import msgspec

# --------------------------------------------------------------------------- #
# Status
# --------------------------------------------------------------------------- #


class IdempotencyStatus(StrEnum):
    """
    Lifecycle state of a recorded idempotency key.

    Only a single terminal state exists today: a key is recorded once its
    handler completes successfully. If a future implementation grows a
    reservation/expiry lifecycle the enum can gain more members without
    breaking callers that only branch on ``PROCESSED``.
    """

    PROCESSED = 'processed'
    """Event was successfully processed — do not reprocess."""


class IdempotencyBackend(StrEnum):
    """Where idempotency keys are stored (``IDEMPOTENCY_BACKEND``)."""

    POSTGRES = 'postgres'
    """``resiliant_processed_events``: the key is claimed FIRST (``INSERT … ON CONFLICT DO
    NOTHING`` in a savepoint of the caller's session) and commits with the business work;
    a concurrent duplicate waits on the unique index. Expiry via ``cleanup_expired``."""

    REDIS = 'redis'
    """Lease protocol (``SET key lease:<token> NX PX lease_ms`` → work → record with the
    retention TTL): recorded outside the business transaction (session ignored); a crash
    leaves a lease that expires, so the event is processed again (never lost)."""


# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class DuplicateEventError(Exception):
    """
    Raised by the idempotency guard when a duplicate event is detected.

    Callers that want to silently skip duplicates should leave
    ``strict_mode``/``raise_on_duplicate`` off (the default). Callers that
    treat a duplicate as a hard error should let this propagate.

    Attributes:
        idempotency_key: The key that was already processed.
        processed_at:    When the original processing was recorded (ISO
                         string), when known.
    """

    def __init__(
        self, idempotency_key: str, processed_at: Optional[str] = None
    ) -> None:
        self.idempotency_key = idempotency_key
        self.processed_at = processed_at
        super().__init__(
            f"Duplicate event detected — key '{idempotency_key}' already processed"
            + (f' at {processed_at}' if processed_at else '')
        )


class IdempotencyInProgressError(Exception):
    """Redis store: another worker holds the lease of this key — nack / retry later, never ack."""

    def __init__(self, idempotency_key: str) -> None:
        self.idempotency_key = idempotency_key
        super().__init__(f"Event '{idempotency_key}' is being processed by another worker")


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #


class IdempotencyConfig(msgspec.Struct, frozen=True):
    """
    Configuration for the idempotency pattern.

    Every tunable lives here so handlers never scatter magic numbers. The
    struct is frozen (immutable) so a single config instance can be shared
    safely across services and workers.

    Attributes
    ----------
    key_separator:
        Character used when joining ``handler_name`` + ``event_id`` into a
        composite idempotency key. Change only if your event IDs or handler
        names can themselves contain the default colon.

    ttl_days:
        How many days a ``processed_events`` row is retained before the
        cleanup job deletes it. Must be long enough that replayed events
        (e.g. from a Kafka offset reset) are still caught — 30 days covers
        almost all realistic at-least-once replay windows.

    cleanup_batch_size:
        Maximum rows deleted per cleanup run. Keeps individual DELETE
        statements short to avoid long-running locks.

    enable_metrics:
        Toggle the in-process counters for processed / duplicate / error
        events exposed on the service.

    log_duplicates:
        When ``True`` (default) a WARNING is emitted for every duplicate key
        detected. Set to ``False`` on very high-throughput paths where
        duplicates are expected and the log volume is undesirable.

    strict_mode:
        When ``True``, ``DuplicateEventError`` is raised instead of silently
        skipping on duplicate. The ``guard()`` context manager exposes its own
        ``raise_on_duplicate`` parameter, which takes precedence per-call.

    lease_ms:
        Redis store only: lease of a key while its work runs (``IDEMPOTENCY_LEASE_MS``).

    Example
    -------
    >>> config = IdempotencyConfig(ttl_days=60, strict_mode=True)
    """

    # Storage
    backend: IdempotencyBackend = IdempotencyBackend.POSTGRES
    """Store implementation used by the service."""

    redis_key_prefix: str = 'idempotency'
    """Namespace of the Redis keys (``<prefix>:<handler_name>:<event_id>``)."""

    # Key construction
    key_separator: str = ':'
    """Separator used to join handler_name and event_id into a composite key."""

    # Retention & cleanup
    ttl_days: int = 30
    """Rows older than this are eligible for deletion by the cleanup job."""

    cleanup_batch_size: int = 500
    """Maximum rows deleted per cleanup run to avoid long locks."""

    # Behaviour flags
    enable_metrics: bool = True
    """Collect in-process counters for processed / duplicate / error events."""

    log_duplicates: bool = True
    """Emit a WARNING log entry each time a duplicate key is detected."""

    strict_mode: bool = False
    """Raise DuplicateEventError instead of silently returning on duplicate."""

    lease_ms: int = 60_000
    """Redis store: how long a worker owns a key while its work runs (``IDEMPOTENCY_LEASE_MS``)."""

    def __post_init__(self) -> None:
        # Validate eagerly so a misconfiguration fails at construction time
        # rather than on the hot path.
        if self.ttl_days < 1:
            raise ValueError(f'ttl_days must be >= 1, got {self.ttl_days}')
        if self.cleanup_batch_size < 1:
            raise ValueError(
                f'cleanup_batch_size must be >= 1, got {self.cleanup_batch_size}'
            )
        if not self.key_separator:
            raise ValueError('key_separator cannot be empty')
        if self.lease_ms < 1000:
            raise ValueError(f'lease_ms must be >= 1000, got {self.lease_ms}')

    @property
    def ttl_seconds(self) -> int:
        """``ttl_days`` expressed in seconds for datetime arithmetic."""
        return self.ttl_days * 86_400


# --------------------------------------------------------------------------- #
# Service contract
# --------------------------------------------------------------------------- #


@runtime_checkable
class IIdempotencyStore(Protocol):
    """Storage behind the idempotency service — one implementation per
    :class:`IdempotencyBackend` (``resiliant.idempotency.stores``).

    ``session`` is the caller's DB session; stores that do not need it (Redis)
    ignore it, so callers always pass the same arguments.
    """

    backend: IdempotencyBackend

    def claim(self, session: Any, idempotency_key: str, scope: dict[str, Any]) -> Any:
        """Async context manager yielding ``True`` when this caller owns the key (run the work),
        ``False`` for a duplicate. The key is recorded only if the block exits cleanly."""
        ...

    async def is_processed(self, session: Any, idempotency_key: str) -> bool:
        """Return ``True`` if the key has already been recorded."""
        ...

    async def mark_processed(
        self,
        session: Any,
        idempotency_key: str,
        event_id: str,
        event_type: str,
        handler_name: str,
        *,
        saga_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        extra_metadata: Optional[dict[str, Any]] = None,
    ) -> bool:
        """Record the key atomically; ``True`` if this call won (inserted), ``False`` on duplicate."""
        ...

    async def cleanup_expired(
        self,
        session: Any,
        *,
        ttl_days: Optional[int] = None,
        batch_size: Optional[int] = None,
    ) -> int:
        """Delete keys older than the TTL; return how many (0 when the store expires keys itself)."""
        ...


@runtime_checkable
class IIdempotencyService(Protocol):
    """
    Application-facing contract of the idempotency service (Postgres or Redis store).

    The idempotency key is always *scoped* to an ``(event_id, handler_name)``
    pair, so the same domain event can be processed independently by multiple
    handlers (fan-out) while still protecting each handler against duplicates.
    Composite key format: ``"<handler_name>:<event_id>"``.

    Preferred usage (context manager)::

        async with service.guard(
            session=session,
            event_id=event.metadata.event_id,
            handler_name="OrderHandler",
        ) as should_process:
            if should_process:
                await do_business_work(...)
                # key is recorded atomically when the block exits cleanly

    Manual usage::

        key = service.build_key(event_id, "OrderHandler")
        if await service.is_processed(session, key):
            return
        await do_business_work(...)
        await service.mark_processed(session, key, event_id, event_type,
                                     "OrderHandler")

    Thread / process safety
    -----------------------
    PostgreSQL's ``ON CONFLICT DO NOTHING`` provides the race-free atomic
    check-and-insert: concurrent workers that both see ``is_processed`` return
    ``False`` will race to insert; exactly one wins and the loser observes a
    duplicate. Handlers should still be designed to tolerate running twice.

    Session/return types are ``Any`` so this contract stays free of any
    persistence-layer import.
    """

    def build_key(self, event_id: str, handler_name: str) -> str:
        """Build a handler-scoped composite key, e.g. ``"OrderHandler:evt_1"``."""
        ...

    async def is_processed(self, session: Any, idempotency_key: str) -> bool:
        """Return ``True`` if the key has already been recorded."""
        ...

    async def mark_processed(
        self,
        session: Any,
        idempotency_key: str,
        event_id: str,
        event_type: str,
        handler_name: str,
        *,
        correlation_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        saga_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> bool:
        """
        Atomically record the key as processed.

        Returns ``True`` when this call inserted the row (won the race) and
        ``False`` when the key already existed (concurrent duplicate).
        """
        ...

    def guard(
        self,
        session: Any,
        event_id: str,
        handler_name: str,
        event_type: str = '',
        *,
        correlation_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        saga_id: Optional[str] = None,
        raise_on_duplicate: bool = False,
    ) -> AbstractAsyncContextManager[bool]:
        """
        Async context manager enforcing idempotency around a block.

        Yields a ``should_process`` flag — run the guarded work only when it is
        truthy (a context manager cannot skip its own body implicitly). On a
        duplicate the guard either raises ``DuplicateEventError`` (when
        ``raise_on_duplicate`` or ``config.strict_mode``) or yields ``False``.
        On clean exit of a fresh key the key is recorded atomically; on
        exception it is *not* recorded so the broker/worker can safely retry.
        """
        ...

    async def cleanup_expired(
        self,
        session: Any,
        *,
        ttl_days: Optional[int] = None,
        batch_size: Optional[int] = None,
    ) -> int:
        """Delete processed-event rows older than the TTL; return rows deleted."""
        ...


__all__ = [
    'DuplicateEventError',
    'IIdempotencyService',
    'IIdempotencyStore',
    'IdempotencyBackend',
    'IdempotencyConfig',
    'IdempotencyStatus',
]
