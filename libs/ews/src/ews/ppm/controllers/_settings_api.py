"""``/api/v1/ppm/settings`` — capability levels and organization PPM settings (Ppm-0009, ADR-20)."""

from __future__ import annotations

from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.http import BaseController, get, patch

from ews.security import RequestScope, current_scope, is_allowed

from .. import _access as access
from .. import _capabilities as caps
from .. import _settings
from ..schemas._settings_api import PpmCapabilityOut, PpmSettingsOut, PpmSettingsUpdate


async def settings_out(
    session: DBAsyncScopedSession, scope: RequestScope
) -> PpmSettingsOut:
    row = await _settings.load(session, scope)
    level = row.level if row else caps.DEFAULT_LEVEL
    enabled = _settings.capabilities_of(row)
    return PpmSettingsOut(
        level=level,
        capabilities=[
            PpmCapabilityOut(
                key=c.key, level=c.level, core=c.core, enabled=enabled[c.key]
            )
            for c in caps.CAPABILITIES
        ],
        overrides=dict(row.capabilities or {}) if row else {},
        settings=_settings.settings_of(row),
        version=row.version if row else 0,
        can_manage=await _settings.can_manage(scope),
        can_create_project=await is_allowed(
            scope, access.PROJECT, 'create', scope.org_domains()
        ),
    )


class PpmSettingsController(BaseController):
    api_prefix = '/api/v1/ppm'
    tags = ('PPM settings',)

    @get(
        '/settings',
        summary='Capability level, enabled capabilities and PPM settings of the organization',
    )
    @db_context_session
    async def get_settings(self, session: DBAsyncScopedSession) -> PpmSettingsOut:
        return await settings_out(session, await current_scope())

    @patch(
        '/settings',
        summary='Change the level, single capabilities or settings (organization admins)',
    )
    @db_context_session(auto_commit=True)
    async def update_settings(
        self, data: PpmSettingsUpdate, session: DBAsyncScopedSession
    ) -> PpmSettingsOut:
        scope = await current_scope()
        await _settings.update(
            session,
            scope,
            version=data.version,
            level=data.level,
            capabilities=data.capabilities,
            settings=data.settings,
        )
        return await settings_out(session, scope)
