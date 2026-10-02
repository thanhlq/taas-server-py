"""
Idempotency service (Postgres or Redis store).

Application-level entry point for at-most-once event processing. It implements
:class:`~foundation.resiliant.idempotency.IIdempotencyService` and orchestrates
the store (``IIdempotencyStore``, chosen by ``IdempotencyConfig.backend``),
in-process metrics, and structured logging behind a single API.

Preferred usage (context manager)::

    idempotency = ResiliantFactory.get_idempotency_service()

    async with idempotency.guard(
        session=session,
        event_id=event.metadata.event_id,
        handler_name="OrderCreatedHandler",
        event_type=event.metadata.event_type,
    ):
        await handle_order_created(event)

The block body runs only once per ``(handler_name, event_id)`` pair: the key is claimed
before the work (same protocol as ``@taas/resiliant``). Duplicates no-op (or raise
``DuplicateEventError`` when strict); if the body raises the claim is undone so the
message can be retried safely.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Literal, Optional

from foundation import BaseService
from foundation.resiliant.idempotency import (
    DuplicateEventError,
    IdempotencyConfig,
    IIdempotencyService,
    IIdempotencyStore,
)

from .idempotency_metrics import IdempotencyMetrics
from .stores import PostgresIdempotencyStore


@dataclass(frozen=True, slots=True)
class GuardOutcome[T]:
    status: Literal['processed', 'duplicate']
    key: str
    result: T | None


class IdempotencyService(IIdempotencyService, BaseService):
    """High-level API for idempotency enforcement.

    Instances are cheap; the store is injected (``resiliant.idempotency.factory``
    picks it from ``config.backend``). With the Postgres store all persistence is
    scoped to the caller's ``session``, so the record commits atomically with the
    surrounding business transaction; the Redis store ignores the session.

    Worker safety
    -------------
    Both stores claim a key atomically (``INSERT … ON CONFLICT DO NOTHING`` /
    ``SET NX``): multiple asyncio tasks or OS processes racing on the same key are
    safe — exactly one wins and the rest detect a duplicate.
    """

    def __init__(
        self,
        config: IdempotencyConfig,
        store: IIdempotencyStore | None = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.store: IIdempotencyStore = store or PostgresIdempotencyStore(config)
        self.metrics = IdempotencyMetrics()

    # ------------------------------------------------------------------
    # Key construction
    # ------------------------------------------------------------------

    def build_key(self, event_id: str, handler_name: str) -> str:
        """
        Build a handler-scoped idempotency key.

        Format: ``"<handler_name><separator><event_id>"``. The handler-name
        prefix means the same domain event can be processed independently by
        multiple handlers without one handler's success blocking another.

        Example:
            >>> svc.build_key("evt_abc123", "DepositHandler")
            'DepositHandler:evt_abc123'
        """
        return f'{handler_name}{self.config.key_separator}{event_id}'

    # ------------------------------------------------------------------
    # Explicit check / mark
    # ------------------------------------------------------------------

    async def is_processed(
        self,
        session: Any,
        idempotency_key: str,
    ) -> bool:
        """Return ``True`` if ``idempotency_key`` has already been recorded."""
        if self.config.enable_metrics:
            self.metrics.record_check()
        return await self.store.is_processed(session, idempotency_key)

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
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Atomically record the key as processed (race-safe).

        Returns ``True`` when this call inserted the row and ``False`` when the
        key already existed (a concurrent duplicate won the race).
        """
        inserted = await self.store.mark_processed(
            session=session,
            idempotency_key=idempotency_key,
            event_id=event_id,
            event_type=event_type,
            handler_name=handler_name,
            saga_id=saga_id,
            correlation_id=correlation_id,
            tenant_id=tenant_id,
            extra_metadata=metadata,
        )

        if self.config.enable_metrics:
            if inserted:
                self.metrics.record_processed()
            else:
                self.metrics.record_duplicate(idempotency_key)

        return inserted

    # ------------------------------------------------------------------
    # Guard (preferred)
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def guard(  # type: ignore[override]
        self,
        session: Any,
        event_id: str,
        handler_name: str,
        event_type: str = '',
        *,
        correlation_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        saga_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        raise_on_duplicate: bool = False,
    ) -> AsyncIterator[bool]:
        """Run a block at most once per ``(handler_name, event_id)`` — same protocol as JS ``guard``.

        The key is **claimed first** (Postgres: insert in a savepoint of ``session``; Redis:
        lease), then the block runs; it yields ``should_process``::

            async with svc.guard(session, event_id, "OrderHandler") as fresh:
                if fresh:
                    await handle_order_created(event)

        * duplicate → yields ``False`` (or raises ``DuplicateEventError`` when strict);
        * the block raises → the claim is undone (savepoint rollback / lease deleted), the
          message can be retried;
        * Redis: another worker holds the lease → ``IdempotencyInProgressError`` (nack).
        """
        key = self.build_key(event_id, handler_name)
        scope = {
            'event_id': event_id,
            'event_type': event_type,
            'handler_name': handler_name,
            'saga_id': saga_id,
            'correlation_id': correlation_id,
            'tenant_id': tenant_id,
            'metadata': metadata,
        }
        if self.config.enable_metrics:
            self.metrics.record_check()
        async with self.store.claim(session, key, scope) as claimed:
            if not claimed:
                if self.config.enable_metrics:
                    self.metrics.record_duplicate(key)
                if self.config.log_duplicates:
                    self.logger.warning(
                        'duplicate skipped: key=%s event=%s handler=%s type=%s', key, event_id, handler_name, event_type or '-'
                    )
                if raise_on_duplicate or self.config.strict_mode:
                    raise DuplicateEventError(idempotency_key=key)
                yield False
                return
            try:
                yield True
            except Exception:
                if self.config.enable_metrics:
                    self.metrics.record_error()
                raise
        if self.config.enable_metrics:
            self.metrics.record_processed()

    async def run_once[T](
        self,
        session: Any,
        *,
        event_id: str,
        handler_name: str,
        work: Callable[[Any], Awaitable[T]],
        event_type: str = '',
        raise_on_duplicate: bool = False,
        **scope: Any,
    ) -> GuardOutcome[T]:
        """JS-style guard: ``work(session)`` at most once; returns ``GuardOutcome(status, key, result)``."""
        async with self.guard(
            session, event_id, handler_name, event_type, raise_on_duplicate=raise_on_duplicate, **scope
        ) as fresh:
            if fresh:
                return GuardOutcome('processed', self.build_key(event_id, handler_name), await work(session))
        return GuardOutcome('duplicate', self.build_key(event_id, handler_name), None)

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    async def cleanup_expired(
        self,
        session: Any,
        *,
        ttl_days: Optional[int] = None,
        batch_size: Optional[int] = None,
    ) -> int:
        """
        Delete processed-event rows older than the TTL.

        Schedule as a low-priority periodic task — never call on the hot path.
        For very large tables, loop until the return value is 0.
        """
        deleted = await self.store.cleanup_expired(
            session,
            ttl_days=ttl_days,
            batch_size=batch_size,
        )

        if deleted and self.config.enable_metrics:
            self.metrics.record_cleanup(deleted)

        self.logger.info('idempotency_cleanup_complete: rows_deleted=%s', deleted)
        return deleted
