"""PPM domain events (Ppm-0008, envelope ADR-25) and the audit store (Ppm-0011, ADR-26).

``emit`` is called inside the business transaction after a change. It:

1. appends the audit row ``taas_ppm_audit_events`` (the Activity read model, Ppm-0520);
2. writes the envelope to the messaging outbox (``resiliant_outbox_messages``, channel = the topic
   ``ppm.<entity>.<event>``, ordering key = the project) when the API registered one — the relay publishes it to Kafka;
3. runs the in-process subscribers (system automation rules: notifications, ADR-17 / ADR-34) in a savepoint, so a
   failing rule never breaks the user's write.

Private personal planning (My Work plans, order, snooze) never emits (Ppm-0008).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid7

from db.models.ppm import PpmAuditEvent
from foundation.db.types import DBAsyncScopedSession

from ews.security import RequestScope

log = logging.getLogger(__name__)

Changes = dict[str, dict[str, Any]]


@dataclass(frozen=True, slots=True)
class Actor:
    """Who caused an event: a user (session), an automation rule, an AI agent run or the system."""

    type: str = 'user'
    ref: str | None = None
    name: str | None = None


@dataclass(slots=True)
class Event:
    """One domain event (ADR-25)."""

    topic: str
    subject_type: str
    subject_id: str
    tenant_id: UUID
    organization_id: UUID | None
    project_id: UUID | None
    actor: Actor
    cause: str = 'ui'
    changes: Changes | None = None
    data: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None
    chain: int = 0
    event_id: str = field(default_factory=lambda: str(uuid7()))
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def envelope(self) -> dict[str, Any]:
        return {
            'topic': self.topic,
            'event_id': self.event_id,
            'occurred_at': self.occurred_at.isoformat(),
            'tenant_id': str(self.tenant_id),
            'organization_id': str(self.organization_id)
            if self.organization_id
            else None,
            'project_id': str(self.project_id) if self.project_id else None,
            'subject': {'type': self.subject_type, 'id': self.subject_id},
            'actor': {
                'type': self.actor.type,
                'id': self.actor.ref,
                'name': self.actor.name,
            },
            'cause': self.cause,
            'chain': self.chain,
            'changes': self.changes or {},
            'data': self.data,
        }


Subscriber = Callable[
    [DBAsyncScopedSession, RequestScope | None, Event], Awaitable[None]
]
_subscribers: list[Subscriber] = []
_chain: ContextVar[int] = ContextVar('ppm_event_chain', default=0)
_cause: ContextVar[str | None] = ContextVar('ppm_event_cause', default=None)
_actor: ContextVar['Actor | None'] = ContextVar('ppm_event_actor', default=None)


def subscribe(fn: Subscriber) -> Subscriber:
    """Register an in-process subscriber (system rules); returns ``fn`` (decorator-friendly)."""
    if fn not in _subscribers:
        _subscribers.append(fn)
    return fn


@contextmanager
def acting_as(actor: Actor, cause: str) -> Iterator[None]:
    """Events emitted inside the block name ``actor`` (an automation rule) and ``cause`` unless given explicitly."""
    token, cause_token = _actor.set(actor), _cause.set(cause)
    try:
        yield
    finally:
        _actor.reset(token)
        _cause.reset(cause_token)


@contextmanager
def caused_by(cause: str) -> Iterator[None]:
    """Events emitted inside the block carry ``cause`` (``quick_add``, ``template``, ``rule``…)."""
    token = _cause.set(cause)
    try:
        yield
    finally:
        _cause.reset(token)


def json_value(value: Any) -> Any:
    """A JSON-safe value for ``changes`` / ``data`` (dates ISO, UUIDs and decimals as strings)."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    if isinstance(value, (list, tuple, set)):
        return [json_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    return value


def diff(before: dict[str, Any], after: dict[str, Any]) -> Changes:
    """``{field: {from, to}}`` of the keys whose value changed."""
    out: Changes = {}
    for key in after:
        old, new = json_value(before.get(key)), json_value(after.get(key))
        if old != new:
            out[key] = {'from': old, 'to': new}
    return out


def snapshot(obj: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    return {f: getattr(obj, f, None) for f in fields}


def user_actor(scope: RequestScope | None) -> Actor:
    if scope is None:
        return Actor('system')
    return Actor('user', scope.email or str(scope.user_id), scope.name or scope.email)


async def _outbox(session: DBAsyncScopedSession, event: Event) -> None:
    try:
        from foundation.resiliant.outbox import IOutboxService
        from foundation.state.service_registry import get_service

        service = get_service(IOutboxService, raise_if_not_found=False)
    except Exception:  # noqa: BLE001 — no registry in this process (tests, scripts)
        service = None
    if service is None:
        return
    await service.save_raw_message(
        session,
        channel=event.topic,
        payload=event.envelope(),
        event_type=event.topic,
        ordering_key=str(event.project_id) if event.project_id else None,
        event_id=event.event_id,
    )


async def emit(
    session: DBAsyncScopedSession,
    scope: RequestScope | None,
    topic: str,
    subject_type: str,
    subject_id: object,
    *,
    project_id: UUID | None = None,
    tenant_id: UUID | None = None,
    organization_id: UUID | None = None,
    changes: Changes | None = None,
    data: dict[str, Any] | None = None,
    actor: Actor | None = None,
    cause: str | None = None,
    reason: str | None = None,
) -> Event:
    """Record one domain event (audit row + outbox + subscribers) in the caller's transaction."""
    tenant = tenant_id or (scope.tenant_id if scope else None)
    if tenant is None:
        raise ValueError(f'event {topic}: no tenant')
    event = Event(
        topic=topic,
        subject_type=subject_type,
        subject_id=str(subject_id),
        tenant_id=tenant,
        organization_id=organization_id or (scope.organization_id if scope else None),
        project_id=project_id,
        actor=actor or _actor.get() or user_actor(scope),
        cause=cause or _cause.get() or 'ui',
        changes=changes or None,
        data=json_value(data or {}),
        reason=reason,
        chain=_chain.get(),
    )
    session.add(
        PpmAuditEvent(
            id=UUID(event.event_id),
            tenant_id=event.tenant_id,
            organization_id=event.organization_id,
            project_id=event.project_id,
            event=event.topic,
            subject_type=event.subject_type,
            subject_id=event.subject_id,
            actor_type=event.actor.type,
            actor_ref=event.actor.ref,
            actor_name=event.actor.name,
            cause=event.cause,
            changes=event.changes,
            data=event.data or None,
            reason=event.reason,
            event_id=event.event_id,
            occurred_at=event.occurred_at,
        )
    )
    await session.flush()
    await _outbox(session, event)
    if _subscribers:
        token = _chain.set(event.chain + 1)
        try:
            for fn in list(_subscribers):
                try:
                    async with session.begin_nested():
                        await fn(session, scope, event)
                except Exception:  # noqa: BLE001 — a rule never breaks the write (logged)
                    log.exception(
                        'ppm event subscriber %s failed on %s',
                        getattr(fn, '__name__', fn),
                        topic,
                    )
        finally:
            _chain.reset(token)
    return event
