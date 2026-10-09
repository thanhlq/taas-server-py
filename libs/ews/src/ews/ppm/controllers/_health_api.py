"""Project health routes (taas-specs/ppm/health/project-health-spec.md §7): current health, history, recalculate,
override, health policy (organization + project exception). Rules in ``ews.ppm._health`` / ``_health_engine``;
capability ``health`` (Ppm-0009) is enforced here."""

from __future__ import annotations

from datetime import date
from typing import Optional

import db.models.ews as ews_models
from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import PermissionDeniedException
from foundation.http import BaseController, delete, get, patch, post, put

from ews.security import RequestScope, current_scope

from .. import _access as access
from .. import _health as health
from .. import _settings
from ..schemas._health_api import (
    PpmHealthDayOut,
    PpmHealthHistoryOut,
    PpmHealthOut,
    PpmHealthOverrideIn,
    PpmHealthPolicyIn,
    PpmHealthPolicyOut,
)


async def _project(
    session: DBAsyncScopedSession, project_id: str, action: str
) -> tuple[RequestScope, ews_models.Project]:
    scope = await current_scope()
    await _settings.require_capability(session, scope, 'health')
    return scope, await access.load_project(
        session, scope, project_id, health.HEALTH, action
    )


async def _out(
    session: DBAsyncScopedSession, scope: RequestScope, project: ews_models.Project, row
) -> PpmHealthOut:
    return PpmHealthOut(
        **health.snapshot_out(row, project, await health.override_of(session, row)),
        **await health.permissions(scope, project),
    )


async def _require_policy(scope: RequestScope) -> None:
    if not await health.can_update_policy(scope):
        raise PermissionDeniedException(detail='ppm.health_policy:update is required')


async def _policy_out(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    project: ews_models.Project | None = None,
) -> PpmHealthPolicyOut:
    policy = await health.policy_for(
        session, scope.organization_id, project.id if project else None
    )
    own = policy.project if project else policy.organization
    return PpmHealthPolicyOut(
        **health.policy_out(policy, own),
        can_update=await health.can_update_policy(scope),
    )


class ProjectHealthController(BaseController):
    """Health of a project: today's ratings + reasons, history, recalculate, manual override, project policy."""

    api_prefix = '/api/v1/projects'
    tags = ('Project health',)

    @get('/{project_id}/health', summary='Today’s health (recomputed when stale)')
    @db_context_session(auto_commit=True)
    async def get_health(
        self, project_id: str, session: DBAsyncScopedSession
    ) -> PpmHealthOut:
        scope, project = await _project(session, project_id, 'read')
        return await _out(
            session, scope, project, await health.current(session, project)
        )

    @get(
        '/{project_id}/health/history',
        summary='Daily snapshots between date_from and date_to (default: the last 90 days)',
    )
    @db_context_session
    async def get_history(
        self,
        project_id: str,
        session: DBAsyncScopedSession,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> PpmHealthHistoryOut:
        _, project = await _project(session, project_id, 'read')
        rows = await health.history(session, project.id, date_from, date_to)
        return PpmHealthHistoryOut(
            items=[
                PpmHealthDayOut(
                    snapshot_date=r.snapshot_date,
                    overall=r.overall,
                    overall_effective=r.overall_effective,
                    schedule=r.schedule,
                    budget=r.budget,
                    resources=r.resources,
                    scope=r.scope,
                    quality=r.quality,
                    risk=r.risk,
                )
                for r in rows
            ]
        )

    @post('/{project_id}/health/recalculate', summary='Recompute now')
    @db_context_session(auto_commit=True)
    async def recalculate(
        self, project_id: str, session: DBAsyncScopedSession
    ) -> PpmHealthOut:
        scope, project = await _project(session, project_id, 'update')
        return await _out(
            session, scope, project, await health.compute(session, project)
        )

    @put(
        '/{project_id}/health/override',
        summary='Set the manual overall rating (reason, expiry)',
    )
    @db_context_session(auto_commit=True)
    async def set_override(
        self, project_id: str, data: PpmHealthOverrideIn, session: DBAsyncScopedSession
    ) -> PpmHealthOut:
        scope, project = await _project(session, project_id, 'override')
        row = await health.set_override(
            session,
            scope,
            project,
            rating=data.rating,
            reason=data.reason,
            expires_on=data.expires_on,
        )
        return await _out(session, scope, project, row)

    @delete(
        '/{project_id}/health/override',
        summary='Clear the manual rating',
        status_code=200,
    )
    @db_context_session(auto_commit=True)
    async def clear_override(
        self, project_id: str, session: DBAsyncScopedSession
    ) -> PpmHealthOut:
        scope, project = await _project(session, project_id, 'override')
        return await _out(
            session,
            scope,
            project,
            await health.clear_override(session, scope, project),
        )

    @get(
        '/{project_id}/health-policy',
        summary='Effective policy of the project and its exception',
    )
    @db_context_session
    async def get_policy(
        self, project_id: str, session: DBAsyncScopedSession
    ) -> PpmHealthPolicyOut:
        scope, project = await _project(session, project_id, 'read')
        return await _policy_out(session, scope, project)

    @patch(
        '/{project_id}/health-policy',
        summary='Set the project exception (thresholds, dimensions)',
    )
    @db_context_session(auto_commit=True)
    async def update_policy(
        self, project_id: str, data: PpmHealthPolicyIn, session: DBAsyncScopedSession
    ) -> PpmHealthPolicyOut:
        scope, project = await _project(session, project_id, 'read')
        await _require_policy(scope)
        await health.update_policy(
            session,
            scope,
            version=data.version,
            thresholds=data.thresholds,
            dimensions=data.dimensions,
            project=project,
        )
        return await _policy_out(session, scope, project)

    @delete(
        '/{project_id}/health-policy',
        summary='Drop the project exception',
        status_code=200,
    )
    @db_context_session(auto_commit=True)
    async def reset_policy(
        self, project_id: str, session: DBAsyncScopedSession
    ) -> PpmHealthPolicyOut:
        scope, project = await _project(session, project_id, 'read')
        await _require_policy(scope)
        await health.reset_policy(session, scope, project)
        return await _policy_out(session, scope, project)


class PpmHealthPolicyController(BaseController):
    """The organization's health policy (thresholds + enabled dimensions)."""

    api_prefix = '/api/v1/ppm'
    tags = ('Project health',)

    @get('/health-policy', summary='Organization health policy')
    @db_context_session
    async def get_policy(self, session: DBAsyncScopedSession) -> PpmHealthPolicyOut:
        scope = await current_scope()
        await _settings.require_capability(session, scope, 'health')
        return await _policy_out(session, scope)

    @patch(
        '/health-policy',
        summary='Change the organization health policy (recomputed in the background)',
    )
    @db_context_session(auto_commit=True)
    async def update_policy(
        self, data: PpmHealthPolicyIn, session: DBAsyncScopedSession
    ) -> PpmHealthPolicyOut:
        scope = await current_scope()
        await _settings.require_capability(session, scope, 'health')
        await _require_policy(scope)
        await health.update_policy(
            session,
            scope,
            version=data.version,
            thresholds=data.thresholds,
            dimensions=data.dimensions,
        )
        return await _policy_out(session, scope)
