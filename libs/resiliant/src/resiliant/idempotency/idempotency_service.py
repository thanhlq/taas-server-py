"""
Database-backed idempotency service.

Application-level entry point for at-most-once event processing. It implements
:class:`~foundation.resiliant.idempotency.IIdempotencyService` and orchestrates
the repository, in-process metrics, and structured logging behind a single API.

Preferred usage (context manager)::

    idempotency = ResiliantFactory.get_idempotency_service()

    async with idempotency.guard(
        session=session,
        event_id=event.metadata.event_id,
        handler_name="OrderCreatedHandler",
        event_type=event.metadata.event_type,
    ):
        await handle_order_created(event)

The block body runs only once per ``(handler_name, event_id)`` pair. Duplicate
invocations silently no-op (or raise ``DuplicateEventError`` when
``raise_on_duplicate=True``). If the body raises, the key is *not* recorded so
the message can be retried safely.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, Optional

from foundation import BaseService
from foundation.resiliant.idempotency import (
    DuplicateEventError,
    IdempotencyConfig,
    IIdempotencyService,
)
from sqlalchemy.ext.asyncio import AsyncSession

from .idempotency_metrics import IdempotencyMetrics
from .idempotency_repository import IdempotencyRepository


class IdempotencyService(IIdempotencyService, BaseService):
    """High-level API for idempotency enforcement.

    Instances are cheap; one repository is created per service (or injected).
    All persistence is scoped to the ``session`` passed by the caller, so the
    idempotency record commits atomically with the surrounding business
    transaction when used inside the ``guard`` context manager.

    Worker safety
    -------------
    The underlying ``INSERT … ON CONFLICT DO NOTHING`` is atomic at the
    database level: multiple asyncio tasks or OS processes racing on the same
    key are safe — exactly one wins and the rest detect a duplicate.
    """

    def __init__(
        self,
        config: IdempotencyConfig,
        repository: IdempotencyRepository | None = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.repository = repository or IdempotencyRepository(config)
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
        session: AsyncSession,
        idempotency_key: str,
    ) -> bool:
        """Return ``True`` if ``idempotency_key`` has already been recorded."""
        if self.config.enable_metrics:
            self.metrics.record_check()
        return await self.repository.is_processed(session, idempotency_key)

    async def mark_processed(
        self,
        session: AsyncSession,
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
        inserted = await self.repository.mark_processed(
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
        session: AsyncSession,
        event_id: str,
        handler_name: str,
        event_type: str = '',
        *,
        correlation_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        saga_id: Optional[str] = None,
        raise_on_duplicate: bool = False,
    ) -> AsyncIterator[bool]:
        """
        Async context manager that enforces idempotency around a block.

        The context manager yields a ``should_process`` flag: run the guarded
        work only when it is truthy. A context manager's body cannot be skipped
        implicitly, so callers must branch on the yielded value (or use
        ``raise_on_duplicate``/``strict_mode`` for exception-based control)::

            async with svc.guard(session, event_id, "OrderHandler") as fresh:
                if fresh:
                    await handle_order_created(event)

        Lifecycle
        ---------
        1. **Entry** — check whether the key is already processed.
           - fresh                → yield ``True``
           - duplicate + strict   → raise ``DuplicateEventError`` (body skipped)
           - duplicate + lenient  → yield ``False`` (caller skips the work)
        2. **Clean exit (fresh)** — record the key atomically.
        3. **Exception (fresh)** — do *not* record the key; re-raise so the
           worker/broker can retry the message safely.

        ``raise_on_duplicate`` overrides ``config.strict_mode`` for this call.
        """
        key = self.build_key(event_id, handler_name)
        effective_strict = raise_on_duplicate or self.config.strict_mode

        # -------------------------------------------------------------- entry
        if self.config.enable_metrics:
            self.metrics.record_check()

        if await self.repository.is_processed(session, key):
            if self.config.enable_metrics:
                self.metrics.record_duplicate(key)
            if self.config.log_duplicates:
                self.logger.warning(
                    'idempotency_duplicate_detected key=%s event_id=%s '
                    'handler=%s type=%s',
                    key,
                    event_id,
                    handler_name,
                    event_type,
                )
            if effective_strict:
                raise DuplicateEventError(idempotency_key=key)
            # Lenient duplicate: hand back False so the caller skips the work.
            yield False
            return

        # --------------------------------------------------------------- body
        try:
            yield True
        except Exception:
            # Do NOT mark as processed — let the message be retried.
            if self.config.enable_metrics:
                self.metrics.record_error()
            raise

        # ---------------------------------------------------------- clean exit
        inserted = await self.repository.mark_processed(
            session=session,
            idempotency_key=key,
            event_id=event_id,
            event_type=event_type,
            handler_name=handler_name,
            saga_id=saga_id,
            correlation_id=correlation_id,
            tenant_id=tenant_id,
        )

        if self.config.enable_metrics:
            if inserted:
                self.metrics.record_processed()
            else:
                self.metrics.record_duplicate(key)

        if not inserted:
            # Another worker raced and won between our check and insert. The
            # body ran here as well — expected under at-least-once delivery;
            # handlers must be idempotent at the business-logic level too.
            self.logger.warning(
                'idempotency_race_on_mark key=%s event_id=%s handler=%s — '
                'two workers processed the same event concurrently; the '
                'handler body ran more than once.',
                key,
                event_id,
                handler_name,
            )

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    async def cleanup_expired(
        self,
        session: AsyncSession,
        *,
        ttl_days: Optional[int] = None,
        batch_size: Optional[int] = None,
    ) -> int:
        """
        Delete processed-event rows older than the TTL.

        Schedule as a low-priority periodic task — never call on the hot path.
        For very large tables, loop until the return value is 0.
        """
        deleted = await self.repository.cleanup_expired(
            session,
            ttl_days=ttl_days,
            batch_size=batch_size,
        )

        if deleted and self.config.enable_metrics:
            self.metrics.record_cleanup(deleted)

        self.logger.info('idempotency_cleanup_complete: rows_deleted=%s', deleted)
        return deleted
