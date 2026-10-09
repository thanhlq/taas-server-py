"""``notify`` — the one interface every app uses to notify people (Ppm-1700, ADR-24).

For each recipient (an IAM user id or an e-mail, ADR-12) minus the actor: one in-app row (``taas_notifications``),
idempotent on ``dedup_key`` (recipient + kind + subject + occurrence, Ppm-1711) and batched with an unread row of the
same ``group_key`` (recipient + kind + subject) younger than ``group_minutes`` (Ppm-1710: ``count`` + latest text);
then the e-mail delivery the recipient's preferences ask for (``instant`` after ``coalesce_seconds``, or ``digest``,
Ppm-1704 / Ppm-1705 / Ppm-1706). Rows are written in the caller's transaction.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from db.models.notifications import (
    Notification,
    NotificationDelivery,
    NotificationPreference,
)
from foundation.db.types import DBAsyncScopedSession
from sqlalchemy import or_, select, text
from sqlalchemy.dialects.postgresql import insert

from ._kinds import kind_of
from ._settings import notification_settings


@dataclass(frozen=True, slots=True)
class Recipient:
    user_id: UUID | None
    email: str | None

    @property
    def key(self) -> str:
        return (self.email or str(self.user_id or '')).lower()


def _uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError, TypeError, AttributeError:
        return None


async def resolve(
    session: DBAsyncScopedSession, refs: Iterable[str]
) -> list[Recipient]:
    """Recipients of user refs (ids or e-mails), de-duplicated, e-mails looked up in the directory."""
    ids = {u for r in refs if (u := _uuid(r))}
    emails = {r.strip().lower() for r in refs if r and '@' in r}
    found: list[Recipient] = []
    if ids or emails:
        rows = await session.execute(
            text(
                'select id, email from taas_user_account '
                'where id = any(:ids) or lower(email) = any(:emails)'
            ),
            {'ids': list(ids), 'emails': list(emails)},
        )
        found = [Recipient(r.id, (r.email or '').lower() or None) for r in rows]
    known_ids = {r.user_id for r in found}
    known_emails = {r.email for r in found if r.email}
    found += [Recipient(None, e) for e in emails if e not in known_emails]
    found += [Recipient(i, None) for i in ids if i not in known_ids]
    out: dict[str, Recipient] = {}
    for r in found:
        out.setdefault(r.key, r)
    return list(out.values())


async def _modes(
    session: DBAsyncScopedSession, user_id: UUID | None, app: str, kind: str
) -> dict[str, str]:
    """``{channel: mode}`` of a user for a kind (``*`` rows apply when no exact row exists)."""
    if user_id is None:
        return {}
    p = NotificationPreference
    rows = await session.execute(
        select(p.kind, p.channel, p.mode).where(
            p.user_id == user_id, p.app == app, or_(p.kind == kind, p.kind == '*')
        )
    )
    out: dict[str, str] = {}
    for row_kind, channel, mode in sorted(rows.all(), key=lambda r: r[0] != '*'):
        if row_kind == '*' and channel in out:
            continue
        out[channel] = mode
    return out


async def notify(
    session: DBAsyncScopedSession,
    *,
    tenant_id: UUID,
    organization_id: UUID | None,
    kind: str,
    recipients: Iterable[str],
    exclude: Iterable[str] = (),
    title: str,
    body: str | None = None,
    link: str | None = None,
    subject_type: str | None = None,
    subject_id: str | None = None,
    project_id: UUID | None = None,
    actor_ref: str | None = None,
    actor_name: str | None = None,
    via: str = 'user',
    occurrence: str,
    data: dict[str, Any] | None = None,
) -> int:
    """Notify ``recipients`` (refs) of one occurrence; returns how many new in-app rows were written."""
    definition = kind_of(kind)
    app = kind.split(':', 1)[0]
    settings = notification_settings()
    excluded = {e.lower() for e in exclude if e}
    now = datetime.now(UTC)
    written = 0
    for r in await resolve(session, [x for x in recipients if x]):
        if r.key in excluded or (r.user_id and str(r.user_id).lower() in excluded):
            continue
        modes = await _modes(session, r.user_id, app, kind)
        in_app = modes.get('in_app', 'instant')
        if definition is not None and definition.mandatory:
            in_app = 'instant'
        email_mode = modes.get(
            'email', definition.email if definition is not None else 'off'
        )
        subject = f'{subject_type or "-"}:{subject_id or "-"}'
        group_key = f'{r.key}|{kind}|{subject}'
        hidden = in_app == 'off'
        row = await session.scalar(
            select(Notification)
            .where(
                Notification.group_key == group_key,
                Notification.read_at.is_(None),
                Notification.created_at
                >= now - timedelta(minutes=settings.group_minutes),
            )
            .order_by(Notification.created_at.desc())
            .limit(1)
        )
        dedup_key = f'{group_key}|{occurrence}'
        if row is not None and row.dedup_key != dedup_key:
            row.count = (row.count or 1) + 1
            row.title, row.body, row.link = title, body, link
            row.actor_ref, row.actor_name = actor_ref, actor_name
            await session.flush()
            continue
        inserted = await session.scalar(
            insert(Notification)
            .values(
                tenant_id=tenant_id,
                organization_id=organization_id,
                recipient_user_id=r.user_id,
                recipient_email=r.email,
                app=app,
                kind=kind,
                subject_type=subject_type,
                subject_id=subject_id,
                project_id=project_id,
                title=title[:500],
                body=(body or None) and body[:4000],
                link=link,
                actor_ref=actor_ref,
                actor_name=actor_name,
                via=via,
                group_key=group_key,
                count=1,
                dedup_key=dedup_key,
                data={**(data or {}), **({'hidden': True} if hidden else {})} or None,
                read_at=now if hidden else None,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=['dedup_key'])
            .returning(Notification.id)
        )
        if inserted is None:
            continue
        written += 1
        if r.email and email_mode in ('instant', 'digest'):
            session.add(
                NotificationDelivery(
                    tenant_id=tenant_id,
                    notification_id=inserted,
                    channel='email' if email_mode == 'instant' else 'digest',
                    recipient_email=r.email,
                    status='pending',
                    scheduled_for=now + timedelta(seconds=settings.coalesce_seconds),
                )
            )
    await session.flush()
    return written
