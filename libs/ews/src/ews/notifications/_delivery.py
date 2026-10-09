"""Background delivery (``NOTIFICATIONS_RUNNER``): instant e-mails (Ppm-1704, 3 retries with back-off, Ppm-1714),
the daily digest at the user's hour (Ppm-1705, never empty) and the scheduled jobs the apps register (e.g. PPM
due-soon / overdue reminders — idempotent through ``dedup_key``). ``api`` = a task of each API process,
``worker`` = ``ews_worker``, ``off`` = nobody (tests call ``run_once``)."""

from __future__ import annotations

import asyncio
import contextlib
import html
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from db.models.notifications import (
    Notification,
    NotificationDelivery,
    NotificationUserSettings,
)
from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from sqlalchemy import select

from ._settings import Runner, notification_settings

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 3
BACKOFF = (60, 300, 1800)

Job = Callable[[DBAsyncScopedSession], Awaitable[int]]


@dataclass(slots=True)
class _Job:
    name: str
    every_seconds: int
    fn: Job
    next_at: float = 0.0


_JOBS: dict[str, _Job] = {}
_RUNNER: list[tuple[asyncio.Task[None], asyncio.Event]] = []


def register_job(name: str, every_seconds: int, fn: Job) -> None:
    """A periodic app job run by the notification runner (its own transaction)."""
    _JOBS[name] = _Job(name, every_seconds, fn)


def link_url(link: str | None) -> str | None:
    if not link:
        return None
    return (
        link if link.startswith('http') else f'{notification_settings().app_url}{link}'
    )


def _email(subject: str, lines: list[tuple[str, str | None, str | None]]):
    """A plain + HTML e-mail: ``lines`` = (title, body, link)."""
    from foundation.email.types import EmailMultiAlternatives

    text_parts, html_parts = [], []
    for title, body, link in lines:
        text_parts.append('\n'.join(p for p in (title, body, link_url(link)) if p))
        url = link_url(link)
        html_parts.append(
            f'<p><strong>{html.escape(title)}</strong>'
            + (f'<br>{html.escape(body)}' if body else '')
            + (
                f'<br><a href="{html.escape(url)}">{html.escape(url)}</a>'
                if url
                else ''
            )
            + '</p>'
        )
    return EmailMultiAlternatives(
        subject=subject,
        body='\n\n'.join(text_parts),
        html_body='\n'.join(html_parts),
    )


async def _send(message, to: str) -> None:
    from foundation.email.factory import EmailServiceFactory

    message.to = [to]
    await EmailServiceFactory.get_email_service().send_message(message)


async def send_instant(session: DBAsyncScopedSession, limit: int = 50) -> int:
    """Send due instant e-mails (one per notification; coalesced repeats carry the latest text)."""
    now = datetime.now(UTC)
    rows = (
        await session.execute(
            select(NotificationDelivery, Notification)
            .join(Notification, Notification.id == NotificationDelivery.notification_id)
            .where(
                NotificationDelivery.channel == 'email',
                NotificationDelivery.status.in_(('pending', 'deferred')),
                NotificationDelivery.scheduled_for <= now,
            )
            .order_by(NotificationDelivery.scheduled_for)
            .limit(limit)
            .with_for_update(of=NotificationDelivery, skip_locked=True)
        )
    ).all()
    sent = 0
    for delivery, note in rows:
        if note.read_at is not None and not (note.data or {}).get('hidden'):
            delivery.status = 'suppressed'  # already seen in the app
            continue
        try:
            subject = (
                note.title
                if (note.count or 1) == 1
                else f'{note.title} (+{note.count - 1})'
            )
            await _send(
                _email(subject, [(note.title, note.body, note.link)]),
                delivery.recipient_email or '',
            )
            delivery.status, delivery.sent_at = 'sent', now
            sent += 1
        except Exception as error:  # noqa: BLE001 — retried with back-off, then failed
            delivery.attempts = (delivery.attempts or 0) + 1
            delivery.error = repr(error)[:500]
            if delivery.attempts >= MAX_ATTEMPTS:
                delivery.status = 'failed'
            else:
                delivery.scheduled_for = now + timedelta(
                    seconds=BACKOFF[delivery.attempts - 1]
                )
    await session.flush()
    return sent


def _digest_due(settings: NotificationUserSettings | None, now: datetime) -> bool:
    zone = ZoneInfo(settings.time_zone) if settings and settings.time_zone else UTC
    hour = settings.digest_hour if settings else 8
    if settings is not None and settings.digest == 'off':
        return False
    local = now.astimezone(zone)
    if settings is not None and settings.digest == 'weekly' and local.weekday() != 0:
        return False
    return local.hour >= hour


async def send_digests(session: DBAsyncScopedSession) -> int:
    """One digest e-mail per recipient whose digest hour passed today, with every pending digest item."""
    now = datetime.now(UTC)
    rows = (
        await session.execute(
            select(NotificationDelivery, Notification)
            .join(Notification, Notification.id == NotificationDelivery.notification_id)
            .where(
                NotificationDelivery.channel == 'digest',
                NotificationDelivery.status == 'pending',
            )
            .with_for_update(of=NotificationDelivery, skip_locked=True)
        )
    ).all()
    by_user: dict[str, list[tuple[NotificationDelivery, Notification]]] = {}
    for delivery, note in rows:
        by_user.setdefault(delivery.recipient_email or '', []).append((delivery, note))
    sent = 0
    for email, items in by_user.items():
        user_id = items[0][1].recipient_user_id
        settings = (
            await session.scalar(
                select(NotificationUserSettings).where(
                    NotificationUserSettings.user_id == user_id
                )
            )
            if user_id
            else None
        )
        if not email or not _digest_due(settings, now):
            continue
        unread = [(d, n) for d, n in items if n.read_at is None]
        if unread:
            try:
                await _send(
                    _email(
                        f'Your digest — {len(unread)} updates',
                        [(n.title, n.body, n.link) for _, n in unread],
                    ),
                    email,
                )
                sent += 1
            except Exception as error:  # noqa: BLE001
                logger.warning(
                    'notifications.digest.failed', extra={'error': repr(error)[:300]}
                )
                continue
        unread_ids = {d.id for d, _ in unread}
        for delivery, _ in items:
            delivery.status = 'sent' if delivery.id in unread_ids else 'suppressed'
            delivery.sent_at = now
    await session.flush()
    return sent


@db_context_session(auto_commit=True)
async def _instant(*, session: DBAsyncScopedSession | None = None) -> int:
    assert session is not None
    return await send_instant(session)


@db_context_session(auto_commit=True)
async def _digests(*, session: DBAsyncScopedSession | None = None) -> int:
    assert session is not None
    return await send_digests(session)


@db_context_session(auto_commit=True)
async def _run_job(job: _Job, *, session: DBAsyncScopedSession | None = None) -> int:
    assert session is not None
    return await job.fn(session)


async def run_once(now_monotonic: float | None = None) -> dict[str, int]:
    """One pass: instant e-mails, digests, due app jobs — each in its own transaction."""
    out: dict[str, int] = {'email': await _instant(), 'digest': await _digests()}
    tick = time.monotonic() if now_monotonic is None else now_monotonic
    for job in list(_JOBS.values()):
        if tick < job.next_at:
            continue
        job.next_at = tick + job.every_seconds
        try:
            out[job.name] = await _run_job(job)
        except Exception:  # noqa: BLE001
            logger.exception('notifications.job.failed %s', job.name)
    return out


async def _loop(stop: asyncio.Event) -> None:
    interval = notification_settings().interval_seconds
    while not stop.is_set():
        try:
            await run_once()
        except Exception:  # noqa: BLE001 — never kill the loop
            logger.exception('notifications.runner.failed')
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval)


def start_runner(runner: Runner) -> asyncio.Task[None] | None:
    if notification_settings().runner != runner or _RUNNER:
        return None
    stop = asyncio.Event()
    task = asyncio.create_task(_loop(stop), name='notifications-runner')
    _RUNNER.append((task, stop))
    return task


async def stop_runner(timeout: float = 10.0) -> None:
    if not _RUNNER:
        return
    task, stop = _RUNNER.pop()
    stop.set()
    try:
        await asyncio.wait_for(task, timeout=timeout)
    except TimeoutError, asyncio.CancelledError:
        task.cancel()
