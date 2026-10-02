"""
Dead-letter service and retry worker (twin of ``@taas/resiliant`` ``dlq/service.ts``).

* :class:`DLQService` — save a failed event inside the caller's transaction (so a
  consumer that gives up on a message records it atomically with its offset /
  state), list, approve / cancel / abandon (operator actions), replay one record
  now, archive, reset stale leases, stats. Never commits.
* :class:`DLQHandlerRegistry` — replays records by ``handler_name``.
* :class:`DLQRetryProcessor` — one retry step: claim due records (lease, own
  transaction, commit), replay each through the registry, resolve it or count the
  failure (backoff, then ``abandoned``).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from logging import Logger
from typing import Any

import msgspec
from foundation import BaseService
from foundation.observability.log_factory import LogFactory
from foundation.resiliant.dlq import (
    DeadLetterConfig,
    DeadLetterError,
    DeadLetterRecord,
    DLQStatus,
    IDeadLetterReplayer,
    IDLQService,
    NewDeadLetter,
)
from sqlalchemy.ext.asyncio import AsyncSession

from resiliant.models import DLQEventTable
from resiliant.sql import db_now, describe_error, exponential_backoff_ms

from .dlq_repository import DLQRepository

_MAX_PAGE = 1000


class DLQService(IDLQService, BaseService):
    """The database-backed dead-letter queue. Every call joins the caller's ``session``."""

    def __init__(
        self,
        config: DeadLetterConfig | None = None,
        repository: DLQRepository | None = None,
    ) -> None:
        super().__init__()
        self.config = config or DeadLetterConfig()
        self.repository = repository or DLQRepository(self.config)

    def max_retries_for(self, handler_name: str, max_retries: int | None = None) -> int:
        """Retry budget: explicit > per-handler > default."""
        if max_retries is not None:
            return max_retries
        return self.config.handler_max_retries.get(handler_name, self.config.max_retries)

    # ----------------------------------------------------------------- writes
    async def save(self, session: AsyncSession, event: NewDeadLetter) -> DLQEventTable:
        """Persist a failed event inside ``session`` (flushed, committed by the caller)."""
        if not event.event_id or not event.handler_name or not event.event_type:
            raise DeadLetterError(
                'a dead letter needs event_id, event_type and handler_name (the retry target)'
            )
        record = await self.repository.insert(
            session, event, max_retries=self.max_retries_for(event.handler_name, event.max_retries)
        )
        self.logger.warning(
            'dead-lettered %s %s for %s (#%s): %s',
            event.event_type,
            event.event_id,
            event.handler_name,
            record.id,
            event.error,
        )
        return record

    async def save_event(
        self,
        session: AsyncSession,
        *,
        handler_name: str,
        error: str,
        event: Any | None = None,
        event_id: str | None = None,
        event_type: str | None = None,
        payload: dict[str, Any] | None = None,
        source_destination: str | None = None,
        source_service: str | None = None,
        headers: dict[str, Any] | None = None,
        max_retries: int | None = None,
        correlation_id: str | None = None,
        user_id: str | None = None,
        tenant_id: str | None = None,
        traceparent: str | None = None,
    ) -> DLQEventTable:
        """Keyword form of :meth:`save`.

        ``event`` (a ``BaseEvent`` or any object with ``event_id`` / ``event_type``)
        fills the event fields — payload, correlation / user / tenant ids, source —
        unless they are passed explicitly. ``traceparent`` goes into ``headers``.
        """
        if event is not None:
            event_id = event_id or getattr(event, 'event_id', None)
            event_type = event_type or getattr(event, 'event_type', None) or type(event).__name__
            if payload is None:
                payload = msgspec.to_builtins(event)
            correlation_id = correlation_id or getattr(event, 'correlation_id', None)
            user_id = user_id or getattr(event, 'user_id', None)
            tenant_id = tenant_id or getattr(event, 'tenant_id', None)
            source_service = source_service or getattr(event, 'source', None)
        if traceparent:
            headers = {**(headers or {}), 'traceparent': traceparent}
        return await self.save(
            session,
            NewDeadLetter(
                event_id=event_id or '',
                event_type=event_type or '',
                handler_name=handler_name,
                payload=payload if payload is not None else {},
                error=error,
                source_destination=source_destination,
                source_service=source_service,
                headers=headers,
                max_retries=max_retries,
                correlation_id=correlation_id,
                user_id=user_id,
                tenant_id=tenant_id,
            ),
        )

    # ------------------------------------------------------------------ reads
    async def get(self, session: AsyncSession, dlq_id: int) -> DLQEventTable | None:
        return await self.repository.get(session, dlq_id)

    async def list(
        self,
        session: AsyncSession,
        *,
        status: DLQStatus | None = None,
        handler_name: str | None = None,
        event_type: str | None = None,
        limit: int | None = None,
        before_id: int | None = None,
    ) -> list[DLQEventTable]:
        """Newest first (id desc), keyset-paginated with ``before_id``; ``limit``
        defaults to ``page_size``, capped at 1000."""
        return await self.repository.list(
            session,
            status=status,
            handler_name=handler_name,
            event_type=event_type,
            before_id=before_id,
            limit=min(limit or self.config.page_size, _MAX_PAGE),
        )

    async def list_pending(
        self, session: AsyncSession, *, limit: int | None = None
    ) -> list[DLQEventTable]:
        """``pending`` records, newest first."""
        return await self.list(session, status=DLQStatus.PENDING, limit=limit)

    async def stats(self, session: AsyncSession) -> dict[str, Any]:
        """Per-status counts + ``oldest_pending_age_ms``."""
        return await self.repository.stats(session)

    async def get_stats(self, session: AsyncSession) -> dict[str, Any]:
        """Alias of :meth:`stats`."""
        return await self.stats(session)

    # ------------------------------------------------------- operator actions
    async def approve(self, session: AsyncSession, dlq_id: int) -> bool:
        """The operator fixed the cause: retry it (also brings back an abandoned
        record, with a fresh budget)."""
        return await self.repository.transition(
            session,
            dlq_id,
            [DLQStatus.PENDING, DLQStatus.ABANDONED],
            DLQStatus.APPROVED,
            retry_count=0,
            next_attempt_at=None,
        )

    async def cancel(self, session: AsyncSession, dlq_id: int) -> bool:
        """Must not be retried (terminal)."""
        return await self.repository.transition(
            session,
            dlq_id,
            [DLQStatus.PENDING, DLQStatus.APPROVED, DLQStatus.ABANDONED],
            DLQStatus.CANCELLED,
        )

    async def abandon(self, session: AsyncSession, dlq_id: int) -> bool:
        """Stop automatic retries of a ``pending`` record."""
        return await self.repository.transition(
            session, dlq_id, [DLQStatus.PENDING], DLQStatus.ABANDONED
        )

    async def replay(
        self, session: AsyncSession, dlq_id: int, replayer: IDeadLetterReplayer
    ) -> DLQStatus:
        """Replay one record now: claim it (pending/approved -> processing), run the
        replayer, then resolve or count the failure.

        Raises:
            DeadLetterError: the record is not retryable (someone else holds or closed it).
        """
        claimed = await self.repository.transition(
            session,
            dlq_id,
            [DLQStatus.PENDING, DLQStatus.APPROVED],
            DLQStatus.PROCESSING,
        )
        record = await self.repository.get(session, dlq_id) if claimed else None
        if record is None:
            raise DeadLetterError(f'dead letter {dlq_id} is not pending or approved')
        return await settle(self.repository, session, record, replayer, self.config, self.logger)

    # ------------------------------------------------------------ maintenance
    async def archive(
        self,
        session: AsyncSession,
        *,
        older_than_days: float | None = None,
        limit: int = 1000,
    ) -> int:
        """Move terminal records older than ``archive_after_days`` to the archive
        table (one batch of ``limit``; loop until 0)."""
        days = self.config.archive_after_days if older_than_days is None else older_than_days
        return await self.repository.archive(session, days, limit)

    async def reset_stale(self, session: AsyncSession) -> int:
        """Return leases older than ``claim_timeout_ms`` (crashed workers) to ``pending``."""
        return await self.repository.reset_stale(session, self.config.claim_timeout_ms)


async def settle(
    repository: DLQRepository,
    session: AsyncSession,
    record: DLQEventTable,
    replayer: IDeadLetterReplayer,
    config: DeadLetterConfig,
    logger: Logger,
) -> DLQStatus:
    """Run ``replayer`` on a ``processing`` record, then resolve it or count the failure."""
    try:
        await replayer.replay(record)
    except Exception as error:
        retry_in_ms = exponential_backoff_ms(
            record.retry_count + 1, config.retry_backoff_multiplier, config.retry_max_interval_ms
        )
        status = await repository.record_failure(session, record, describe_error(error), retry_in_ms)
        logger.warning(
            'dead letter #%s (%s) retry %s/%s failed -> %s: %s',
            record.id,
            record.handler_name,
            record.retry_count + 1,
            record.max_retries,
            status,
            describe_error(error),
        )
        return status
    ok = await repository.transition(
        session,
        record.id,
        [DLQStatus.PROCESSING],
        DLQStatus.RESOLVED,
        processed_at=db_now(),
        next_attempt_at=None,
    )
    if not ok:
        raise DeadLetterError(f'dead letter {record.id} changed while it was replayed')
    return DLQStatus.RESOLVED


DeadLetterHandler = Callable[[DeadLetterRecord], Awaitable[None]]


class DLQHandlerRegistry(IDeadLetterReplayer):
    """Replays records by ``handler_name``. A record for an unknown handler fails
    (and is eventually abandoned)."""

    def __init__(self) -> None:
        self._handlers: dict[str, DeadLetterHandler] = {}

    def register(self, handler_name: str, handler: DeadLetterHandler) -> DLQHandlerRegistry:
        self._handlers[handler_name] = handler
        return self

    async def replay(self, record: DeadLetterRecord) -> None:
        handler = self._handlers.get(record.handler_name)
        if handler is None:
            raise DeadLetterError(f'no dead-letter handler registered for "{record.handler_name}"')
        await handler(record)


@dataclass
class DLQRetryResult:
    claimed: int = 0
    resolved: int = 0
    failed: int = 0
    abandoned: int = 0


class DLQRetryProcessor:
    """One automatic retry step; drive it from a schedule job or a loop.

    It owns its transactions (``session_factory``): the claim commits on its own —
    a replay may be slow and must not hold row locks — then every record is
    settled and committed in a session of its own.
    """

    def __init__(
        self,
        *,
        service: DLQService,
        session_factory: Callable[[], AsyncSession],
        replayer: IDeadLetterReplayer,
        logger: Logger | None = None,
    ) -> None:
        self.service = service
        self.session_factory = session_factory
        self.replayer = replayer
        self.logger = logger or LogFactory().get_logger('DLQRetryProcessor')

    async def process_batch(self) -> DLQRetryResult:
        async with self.session_factory() as session:
            async with session.begin():
                records = await self.service.repository.claim_due(
                    session, self.service.config.batch_size
                )
                # Detach before the commit: the rows keep their loaded state
                # (no refresh after commit) while handlers run outside any transaction.
                session.expunge_all()
        result = DLQRetryResult(claimed=len(records))
        for record in records:
            async with self.session_factory() as session:
                status = await settle(
                    self.service.repository,
                    session,
                    record,
                    self.replayer,
                    self.service.config,
                    self.logger,
                )
                await session.commit()
            if status == DLQStatus.RESOLVED:
                result.resolved += 1
            elif status == DLQStatus.ABANDONED:
                result.abandoned += 1
            else:
                result.failed += 1
        return result


__all__ = [
    'DLQHandlerRegistry',
    'DLQRetryProcessor',
    'DLQRetryResult',
    'DLQService',
    'DeadLetterHandler',
    'settle',
]
