"""PPM settings of an organization (``taas_ppm_settings``): capability level + overrides (Ppm-0009) and the
organization's PPM preferences. Read by every member, changed by holders of ``ppm.settings:manage``
(organization admins), versioned (``version`` must match on update: 409 ``stale_settings``)."""

from __future__ import annotations

from typing import Any

from db.models.ppm import PpmSettings
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException, PermissionDeniedException
from sqlalchemy import select

from ews.authz import EwsResources
from ews.security import RequestScope, is_allowed
from ews.shared import ConflictException

from . import _time_settings as time_settings
from . import _capabilities as caps
from . import _events as events

SETTINGS = EwsResources.PPM_SETTINGS.value

EDITOR_MODES = ('visual', 'markdown')
"""Writing modes of descriptions (shared document editor): ``editors.enabled`` lists the offered ones."""
DEFAULT_SETTINGS: dict[str, Any] = {
    'editors': {'default': 'visual', 'enabled': ['visual', 'markdown']},
}


async def load(
    session: DBAsyncScopedSession, scope: RequestScope
) -> PpmSettings | None:
    return await session.scalar(
        select(PpmSettings).where(PpmSettings.organization_id == scope.organization_id)
    )


def settings_of(row: PpmSettings | None) -> dict[str, Any]:
    """Organization settings with the defaults filled in."""
    stored = (row.settings if row else None) or {}
    return {**DEFAULT_SETTINGS, **stored}


def capabilities_of(row: PpmSettings | None) -> dict[str, bool]:
    return caps.effective(
        row.level if row else caps.DEFAULT_LEVEL, row.capabilities if row else None
    )


async def enabled(session: DBAsyncScopedSession, scope: RequestScope, key: str) -> bool:
    return capabilities_of(await load(session, scope)).get(key, False)


async def require_capability(
    session: DBAsyncScopedSession, scope: RequestScope, key: str
) -> None:
    """403 ``capability_disabled`` when the organization switched the capability off (Ppm-0009)."""
    if not await enabled(session, scope, key):
        raise PermissionDeniedException(
            detail=f'the capability {key!r} is disabled for this organization',
            extra={'code': 'capability_disabled', 'capability': key},
        )


async def can_manage(scope: RequestScope) -> bool:
    return await is_allowed(scope, SETTINGS, 'manage', scope.org_domains())


def _clean_editors(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ClientException(detail='editors must be an object {default, enabled}')
    enabled_modes = [m for m in value.get('enabled') or [] if m in EDITOR_MODES]
    if not enabled_modes:
        raise ClientException(
            detail=f'editors.enabled needs at least one of {", ".join(EDITOR_MODES)}'
        )
    default = (
        value.get('default')
        if value.get('default') in enabled_modes
        else enabled_modes[0]
    )
    return {'default': default, 'enabled': list(dict.fromkeys(enabled_modes))}


def clean_settings(value: dict[str, Any]) -> dict[str, Any]:
    """Known setting groups, validated (unknown keys are refused: 400)."""
    out: dict[str, Any] = {}
    for key, item in value.items():
        if key == 'editors':
            out['editors'] = _clean_editors(item)
        elif key == 'time':
            out['time'] = time_settings.clean(item)
        else:
            raise ClientException(detail=f'unknown PPM setting {key!r}')
    return out


async def update(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    *,
    version: int | None,
    level: int | None = None,
    capabilities: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
) -> PpmSettings:
    if not await can_manage(scope):
        raise PermissionDeniedException(detail=f'missing permission {SETTINGS}:manage')
    row = await load(session, scope)
    if row is None:
        row = PpmSettings(
            tenant_id=scope.tenant_id,
            organization_id=scope.organization_id,
            level=caps.DEFAULT_LEVEL,
            capabilities={},
            settings={},
            version=0,
        )
        session.add(row)
    elif version is not None and version != row.version:
        raise ConflictException(
            detail='the PPM settings changed meanwhile: reload them',
            extra={'code': 'stale_settings'},
        )
    before = {
        'level': row.level,
        'capabilities': dict(row.capabilities or {}),
        'settings': dict(row.settings or {}),
    }
    if level is not None:
        if level not in caps.LEVELS:
            raise ClientException(detail='level must be 1, 2, 3 or 4')
        row.level = level
    if capabilities is not None:
        merged = {**(row.capabilities or {}), **capabilities}
        merged = {k: v for k, v in merged.items() if v is not None}
        row.capabilities = caps.clean_overrides(row.level, merged)
    elif level is not None:
        row.capabilities = caps.clean_overrides(row.level, dict(row.capabilities or {}))
    if settings is not None:
        cleaned = clean_settings(settings)
        if 'time' in cleaned:
            cleaned['time'] = time_settings.merge((row.settings or {}).get('time'), cleaned['time'])
        row.settings = {**(row.settings or {}), **cleaned}
    row.version = (row.version or 0) + 1
    row.updated_by = scope.email or str(scope.user_id)
    await session.flush()
    after = {
        'level': row.level,
        'capabilities': row.capabilities,
        'settings': row.settings,
    }
    await events.emit(
        session,
        scope,
        'ppm.settings.updated',
        'settings',
        scope.organization_id,
        changes=events.diff(before, after),
    )
    return row
