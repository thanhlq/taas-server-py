"""``/api/v1/notifications`` — the caller's inbox (top-nav bell), read state, preferences and delivery settings."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from db.models.notifications import (
    Notification,
    NotificationPreference,
    NotificationUserSettings,
)
from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException, NotFoundException
from foundation.http import BaseController, delete, get, post, put, status
from sqlalchemy import ColumnElement, and_, func, or_, select, update

from ews.security import RequestScope, current_scope
from ews.shared import parse_uuid

from .._kinds import CHANNELS, MODES, all_kinds, kind_of
from ..schemas import (
    NotificationCountOut,
    NotificationKindOut,
    NotificationOut,
    NotificationPreferenceOut,
    NotificationPreferencesIn,
    NotificationPreferencesOut,
    NotificationSettingsIo,
)

N = Notification


def mine(scope: RequestScope) -> ColumnElement[bool]:
    """Rows of the caller (user id, or the e-mail for recipients known by e-mail) in the tenant, not hidden."""
    who = [N.recipient_user_id == scope.user_id]
    if scope.email:
        who.append(func.lower(N.recipient_email) == scope.email.lower())
    return and_(
        N.tenant_id == scope.tenant_id,
        or_(*who),
        or_(N.data.is_(None), N.data['hidden'].as_boolean().is_not(True)),
    )


def _out(n: Notification) -> NotificationOut:
    return NotificationOut(
        id=str(n.id),
        app=n.app,
        kind=n.kind,
        title=n.title,
        body=n.body,
        link=n.link,
        subject_type=n.subject_type,
        subject_id=n.subject_id,
        project_id=str(n.project_id) if n.project_id else None,
        actor_ref=n.actor_ref,
        actor_name=n.actor_name,
        via=n.via,
        count=n.count or 1,
        data={k: v for k, v in (n.data or {}).items() if k != 'hidden'},
        read_at=n.read_at,
        created_at=n.created_at,
    )


def _settings_io(row: NotificationUserSettings | None) -> NotificationSettingsIo:
    if row is None:
        return NotificationSettingsIo()
    return NotificationSettingsIo(
        time_zone=row.time_zone,
        digest=row.digest,
        digest_hour=row.digest_hour,
        quiet_from=row.quiet_from,
        quiet_to=row.quiet_to,
        quiet_weekends=row.quiet_weekends,
    )


def _check_settings(value: NotificationSettingsIo) -> None:
    try:
        ZoneInfo(value.time_zone)
    except ZoneInfoNotFoundError, ValueError:
        raise ClientException(detail=f'unknown time zone {value.time_zone!r}') from None
    if value.digest not in ('daily', 'weekly', 'off'):
        raise ClientException(detail='digest must be daily, weekly or off')
    for hour in (value.digest_hour, value.quiet_from, value.quiet_to):
        if hour is not None and not 0 <= hour <= 23:
            raise ClientException(detail='hours are 0 … 23')


async def _preferences_out(
    session: DBAsyncScopedSession, scope: RequestScope
) -> NotificationPreferencesOut:
    p = NotificationPreference
    rows = await session.scalars(select(p).where(p.user_id == scope.user_id))
    settings = await session.scalar(
        select(NotificationUserSettings).where(
            NotificationUserSettings.user_id == scope.user_id
        )
    )
    return NotificationPreferencesOut(
        kinds=[
            NotificationKindOut(
                key=k.key, app=k.app, email=k.email, mandatory=k.mandatory
            )
            for k in all_kinds()
        ],
        preferences=[
            NotificationPreferenceOut(
                app=r.app, kind=r.kind, channel=r.channel, mode=r.mode
            )
            for r in rows.all()
        ],
        settings=_settings_io(settings),
    )


class NotificationController(BaseController):
    api_prefix = '/api/v1/notifications'
    tags = ('Notifications',)

    @get('/', summary="The caller's notifications, newest first")
    @db_context_session
    async def list_notifications(
        self,
        session: DBAsyncScopedSession,
        unread: bool = False,
        app: str | None = None,
        before: datetime | None = None,
        limit: int = 30,
    ) -> list[NotificationOut]:
        scope = await current_scope()
        query = select(N).where(mine(scope))
        if unread:
            query = query.where(N.read_at.is_(None))
        if app:
            query = query.where(N.app == app)
        if before is not None:
            query = query.where(N.created_at < before)
        rows = await session.scalars(
            query.order_by(N.created_at.desc()).limit(max(1, min(limit, 100)))
        )
        return [_out(n) for n in rows.all()]

    @get('/unread-count', summary='Unread notifications of the caller (bell badge)')
    @db_context_session
    async def unread_count(
        self, session: DBAsyncScopedSession, app: str | None = None
    ) -> NotificationCountOut:
        scope = await current_scope()
        query = select(func.count(N.id)).where(mine(scope), N.read_at.is_(None))
        if app:
            query = query.where(N.app == app)
        return NotificationCountOut(unread=int(await session.scalar(query) or 0))

    @post('/{notification_id}/read', summary='Mark one notification read')
    @db_context_session(auto_commit=True)
    async def mark_read(
        self, notification_id: str, session: DBAsyncScopedSession
    ) -> NotificationOut:
        scope = await current_scope()
        row = await session.scalar(
            select(N).where(
                N.id == parse_uuid(notification_id, 'notification'), mine(scope)
            )
        )
        if row is None:
            raise NotFoundException(detail='notification not found')
        if row.read_at is None:
            row.read_at = datetime.now(UTC)
            await session.flush()
        return _out(row)

    @post('/{notification_id}/unread', summary='Mark one notification unread')
    @db_context_session(auto_commit=True)
    async def mark_unread(
        self, notification_id: str, session: DBAsyncScopedSession
    ) -> NotificationOut:
        scope = await current_scope()
        row = await session.scalar(
            select(N).where(
                N.id == parse_uuid(notification_id, 'notification'), mine(scope)
            )
        )
        if row is None:
            raise NotFoundException(detail='notification not found')
        row.read_at = None
        await session.flush()
        return _out(row)

    @post('/read-all', summary='Mark every notification read (optionally of one app)')
    @db_context_session(auto_commit=True)
    async def read_all(
        self, session: DBAsyncScopedSession, app: str | None = None
    ) -> NotificationCountOut:
        scope = await current_scope()
        condition = and_(mine(scope), N.read_at.is_(None))
        if app:
            condition = and_(condition, N.app == app)
        result = await session.execute(
            update(N).where(condition).values(read_at=datetime.now(UTC))
        )
        del result
        return NotificationCountOut(unread=0)

    @get(
        '/preferences', summary="Kinds, the caller's preferences and delivery settings"
    )
    @db_context_session
    async def preferences(
        self, session: DBAsyncScopedSession
    ) -> NotificationPreferencesOut:
        return await _preferences_out(session, await current_scope())

    @put(
        '/preferences',
        summary="Replace the caller's preferences (and delivery settings)",
    )
    @db_context_session(auto_commit=True)
    async def set_preferences(
        self, data: NotificationPreferencesIn, session: DBAsyncScopedSession
    ) -> NotificationPreferencesOut:
        scope = await current_scope()
        p = NotificationPreference
        seen: set[tuple[str, str, str]] = set()
        rows: list[NotificationPreference] = []
        for pref in data.preferences:
            if pref.channel not in CHANNELS or pref.mode not in MODES:
                raise ClientException(
                    detail=f'unknown channel / mode {pref.channel}/{pref.mode}'
                )
            kind = kind_of(pref.kind) if pref.kind != '*' else None
            if pref.kind != '*' and kind is None:
                raise ClientException(detail=f'unknown notification kind {pref.kind!r}')
            if (
                kind is not None
                and kind.mandatory
                and pref.channel == 'in_app'
                and pref.mode == 'off'
            ):
                raise ClientException(
                    detail=f'{pref.kind} cannot be switched off in the app'
                )
            key = (pref.app, pref.kind, pref.channel)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                p(
                    tenant_id=scope.tenant_id,
                    user_id=scope.user_id,
                    app=pref.app,
                    kind=pref.kind,
                    channel=pref.channel,
                    mode=pref.mode,
                )
            )
        for old in (
            await session.scalars(select(p).where(p.user_id == scope.user_id))
        ).all():
            await session.delete(old)
        await session.flush()
        session.add_all(rows)
        if data.settings is not None:
            _check_settings(data.settings)
            current = await session.scalar(
                select(NotificationUserSettings).where(
                    NotificationUserSettings.user_id == scope.user_id
                )
            )
            if current is None:
                current = NotificationUserSettings(
                    tenant_id=scope.tenant_id, user_id=scope.user_id
                )
                session.add(current)
            current.email = scope.email
            for field in (
                'time_zone',
                'digest',
                'digest_hour',
                'quiet_from',
                'quiet_to',
                'quiet_weekends',
            ):
                setattr(current, field, getattr(data.settings, field))
        await session.flush()
        return await _preferences_out(session, scope)

    @delete(
        '/preferences',
        status_code=status.HTTP_204_NO_CONTENT,
        summary='Back to the defaults',
    )
    @db_context_session(auto_commit=True)
    async def reset_preferences(self, session: DBAsyncScopedSession) -> None:
        scope = await current_scope()
        p = NotificationPreference
        for old in (
            await session.scalars(select(p).where(p.user_id == scope.user_id))
        ).all():
            await session.delete(old)
