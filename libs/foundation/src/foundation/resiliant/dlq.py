"""
Dead-letter queue — contracts only (implementation: ``resiliant.dlq``).

Twin of ``@taas/foundation/resiliant`` ``dlq.ts``: both stacks share the
``resiliant_dlq_events`` tables, so statuses, transitions and policy defaults are
the same.

Keeps the events a handler could not process after its in-process retry budget,
with everything needed to replay them (``handler_name`` + payload), so an
operator can inspect, fix, approve, retry, cancel or abandon them. Nothing is
ever deleted from the live table except by archiving terminal rows: a financial
event that failed must stay traceable.

Lifecycle (every change is a compare-and-set on the current status)::

    pending ──claim──> processing ──resolve──> resolved ──archive──> (archive table)
       │  ^                 │
       │  └──── fail ───────┤ (budget left)
       │                    └── fail (budget spent) ──> abandoned
       ├── approve (operator fixed it) ──> approved ──claim──> processing
       └── cancel ──> cancelled
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

import msgspec

# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class DeadLetterError(Exception):
    """Base class for DLQ errors (illegal transition, missing record, bad input)."""


class DeadLetterReplayError(DeadLetterError):
    """Replaying a record back to its handler failed."""


# --------------------------------------------------------------------------- #
# Statuses and transitions
# --------------------------------------------------------------------------- #


class DLQStatus(StrEnum):
    """Status of a dead letter (``text`` + CHECK in the shared table)."""

    PENDING = 'pending'
    """Waiting for an (automatic) retry."""

    APPROVED = 'approved'
    """An operator fixed the cause and cleared the record for another try."""

    CANCELLED = 'cancelled'
    """An operator decided it must not be retried (terminal)."""

    PROCESSING = 'processing'
    """Claimed by a retry worker (lease)."""

    RESOLVED = 'resolved'
    """A retry succeeded (terminal)."""

    ABANDONED = 'abandoned'
    """Retry budget exhausted (an operator may still approve or cancel it)."""


_S = DLQStatus

DLQ_TRANSITIONS: Mapping[DLQStatus, tuple[DLQStatus, ...]] = MappingProxyType(
    {
        _S.PENDING: (_S.PROCESSING, _S.APPROVED, _S.CANCELLED, _S.ABANDONED),
        _S.APPROVED: (_S.PROCESSING, _S.CANCELLED),
        _S.PROCESSING: (_S.RESOLVED, _S.PENDING, _S.ABANDONED),
        _S.ABANDONED: (_S.APPROVED, _S.CANCELLED),
        _S.RESOLVED: (),
        _S.CANCELLED: (),
    }
)
"""Allowed ``from -> to`` changes; anything else is refused before any SQL."""

ARCHIVABLE_DLQ_STATUSES: tuple[DLQStatus, ...] = (_S.RESOLVED, _S.CANCELLED, _S.ABANDONED)
"""Terminal rows the archiver may move out of the live table."""

RETRYABLE_DLQ_STATUSES: tuple[DLQStatus, ...] = (_S.PENDING, _S.APPROVED)
"""Rows a retry worker may claim (the predicate of ``resiliant_dlq_events_due_idx``)."""


def can_transition_dlq(from_status: DLQStatus | str, to_status: DLQStatus | str) -> bool:
    """True when ``from_status -> to_status`` is in :data:`DLQ_TRANSITIONS`."""
    try:
        return DLQStatus(to_status) in DLQ_TRANSITIONS[DLQStatus(from_status)]
    except ValueError:
        return False


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #


class DeadLetterRecord(Protocol):
    """A stored dead letter (the ``resiliant_dlq_events`` row, e.g. ``DLQEventTable``)."""

    id: int
    event_id: str
    event_type: str
    handler_name: str
    """The handler that failed; the retry worker routes on it."""
    source_destination: str | None
    source_service: str | None
    payload: dict[str, Any]
    headers: dict[str, Any] | None
    status: DLQStatus
    retry_count: int
    max_retries: int
    original_error: str
    last_error: str | None
    correlation_id: str | None
    user_id: str | None
    tenant_id: str | None
    failed_at: datetime
    processed_at: datetime | None
    next_attempt_at: datetime | None
    created_at: datetime
    updated_at: datetime


class NewDeadLetter(msgspec.Struct, kw_only=True, frozen=True):
    """A failed event to park in the DLQ."""

    event_id: str
    event_type: str
    handler_name: str
    """The retry target — keep it stable."""
    payload: dict[str, Any]
    error: str
    source_destination: str | None = None
    """Original topic / queue."""
    source_service: str | None = None
    headers: dict[str, Any] | None = None
    max_retries: int | None = None
    """Default: the per-handler limit, else ``DeadLetterConfig.max_retries``."""
    correlation_id: str | None = None
    user_id: str | None = None
    tenant_id: str | None = None
    failed_at: datetime | None = None
    """Default: now (database clock)."""


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #


class DeadLetterConfig(msgspec.Struct, frozen=True):
    """DLQ policy (``DLQ_*`` environment, see ``resiliant.dlq.dlq_settings``).

    Same fields and defaults as ``DeadLetterConfigT`` in ``@taas/foundation``;
    invalid values raise ``ValueError`` at construction.
    """

    batch_size: int = 50
    """Rows a retry step claims at once."""

    page_size: int = 100
    """Default ``list`` page size (capped at 1000)."""

    max_retries: int = 3
    """Default retry budget of a dead letter."""

    retry_backoff_multiplier: float = 2.0
    """Retry n waits ``multiplier ** n`` seconds, capped by ``retry_max_interval_ms``."""

    retry_max_interval_ms: int = 60_000

    claim_timeout_ms: int = 300_000
    """A ``processing`` row older than this belonged to a crashed worker and returns to ``pending``."""

    archive_after_days: int = 30
    """Terminal rows older than this move to the archive table."""

    handler_max_retries: dict[str, int] = {}
    """Per-handler retry limits, e.g. ``{'OrderHandler': 5}``."""

    def __post_init__(self) -> None:
        for key in ('batch_size', 'page_size', 'max_retries', 'archive_after_days'):
            value = getattr(self, key)
            if not _is_int(value) or value < 1:
                raise ValueError(f'dlq {key} must be an integer >= 1, got {value!r}')
        if not (self.retry_backoff_multiplier >= 1):
            raise ValueError(
                f'dlq retry_backoff_multiplier must be >= 1, got {self.retry_backoff_multiplier!r}'
            )
        for handler, limit in self.handler_max_retries.items():
            if not _is_int(limit) or limit < 1:
                raise ValueError(
                    f'dlq handler_max_retries.{handler} must be an integer >= 1, got {limit!r}'
                )


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


# --------------------------------------------------------------------------- #
# Protocols
# --------------------------------------------------------------------------- #


@runtime_checkable
class IDeadLetterReplayer(Protocol):
    """Re-runs one record, typically through the handler named by ``record.handler_name``."""

    async def replay(self, record: DeadLetterRecord) -> None: ...


@runtime_checkable
class IDLQService(Protocol):
    """
    The database-backed dead-letter queue (implementation: ``resiliant.dlq.DLQService``).

    Every call takes the caller's ``session`` and joins its transaction (nothing is
    committed here). Session / record types are loose (``Any``) so this module stays
    free of persistence imports.
    """

    async def save(self, session: Any, event: NewDeadLetter) -> Any:
        """Persist a failed event inside ``session`` (commits with the caller)."""
        ...

    async def save_event(
        self,
        session: Any,
        *,
        handler_name: str,
        error: str,
        event: Any | None = None,
        event_id: str | None = None,
        event_type: str | None = None,
        payload: dict[str, Any] | None = None,
        source_destination: str | None = None,
        headers: dict[str, Any] | None = None,
        max_retries: int | None = None,
        correlation_id: str | None = None,
        traceparent: str | None = None,
    ) -> Any:
        """Keyword form of :meth:`save`; ``event`` (a ``BaseEvent``) fills the event fields."""
        ...

    async def get(self, session: Any, dlq_id: int) -> Any:
        """One record by id (or ``None``)."""
        ...

    async def list(
        self,
        session: Any,
        *,
        status: DLQStatus | None = None,
        handler_name: str | None = None,
        event_type: str | None = None,
        limit: int | None = None,
        before_id: int | None = None,
    ) -> Any:
        """Newest first, keyset-paginated with ``before_id``."""
        ...

    async def approve(self, session: Any, dlq_id: int) -> bool: ...

    async def cancel(self, session: Any, dlq_id: int) -> bool: ...

    async def abandon(self, session: Any, dlq_id: int) -> bool: ...

    async def replay(self, session: Any, dlq_id: int, replayer: IDeadLetterReplayer) -> DLQStatus:
        """Claim, replay and resolve (or count a failure) one record now."""
        ...

    async def stats(self, session: Any) -> dict[str, Any]:
        """Per-status counts plus ``oldest_pending_age_ms``."""
        ...


__all__ = [
    'ARCHIVABLE_DLQ_STATUSES',
    'DLQ_TRANSITIONS',
    'DLQStatus',
    'DeadLetterConfig',
    'DeadLetterError',
    'DeadLetterRecord',
    'DeadLetterReplayError',
    'IDLQService',
    'IDeadLetterReplayer',
    'NewDeadLetter',
    'RETRYABLE_DLQ_STATUSES',
    'can_transition_dlq',
]
