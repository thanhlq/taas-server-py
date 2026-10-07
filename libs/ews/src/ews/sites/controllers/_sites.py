"""``/api/v1/sites`` — sites of the request's organization, theme, members, export / import, audit."""

from __future__ import annotations

from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.http import BaseController, delete, get, patch, post, put, status
from sqlalchemy import select

from ews.authz import EwsResources
from ews.security import authorize, current_scope

from .. import _access as access
from .. import _members as members
from .. import _service as svc
from .._settings import sites_settings
from .._templates import templates
from ..schemas import (
    AuditOut,
    CandidateOut,
    MemberOut,
    MemberUpsert,
    RoleOut,
    SitesAccessOut,
    SiteCreate,
    SiteExportOut,
    SiteImport,
    SiteOut,
    SiteUpdate,
    TemplateOut,
    ThemeOut,
    ThemeUpdate,
)

R = EwsResources


class SitesController(BaseController):
    api_prefix = '/api/v1/sites'
    tags = ('Site Builder',)

    @get('/access', summary='Can the caller open the Site Builder (and create sites)?')
    @db_context_session
    async def access(self, session: DBAsyncScopedSession) -> SitesAccessOut:
        scope = await current_scope()
        allowed, can_create = await svc.can_open_app(scope)
        return SitesAccessOut(
            allowed=allowed, can_create=can_create, sites_domain=sites_settings().domain, organization_slug=scope.organization.slug
        )

    @get('/templates', summary='Starter templates')
    async def list_templates(self) -> list[TemplateOut]:
        await current_scope()
        return [
            TemplateOut(
                key=t['key'], name=t['name'], description=t['description'], colors=t['theme']['colors'],
                fonts=t['theme']['fonts'], pages=[p['title'] for p in t['pages'] if not p.get('not_found')],
            )
            for t in templates()
        ]

    @get('/roles', summary='Roles that can be granted on a site')
    async def list_roles(self) -> list[RoleOut]:
        await current_scope()
        return members.site_roles()

    @get('/')
    @db_context_session
    async def list_sites(self, session: DBAsyncScopedSession, include_archived: bool = True) -> list[SiteOut]:
        scope = await current_scope()
        return await svc.list_sites(session, scope, include_archived=include_archived)

    @post('/', status_code=status.HTTP_201_CREATED, summary='Create a site (blank or from a template)')
    @db_context_session(auto_commit=True)
    async def create_site(self, data: SiteCreate, session: DBAsyncScopedSession) -> SiteOut:
        scope = await current_scope()
        await authorize(scope, R.SITE.value, 'create')
        site = await svc.create_site(session, scope, data)
        return await svc.site_out(session, scope, site)

    @post('/import', status_code=status.HTTP_201_CREATED, summary='Create a site from an export (Site-0007)')
    @db_context_session(auto_commit=True)
    async def import_site(self, data: SiteImport, session: DBAsyncScopedSession) -> SiteOut:
        scope = await current_scope()
        await authorize(scope, R.SITE.value, 'create')
        site = await svc.import_site(session, scope, data.name, data.slug, data.export)
        return await svc.site_out(session, scope, site)

    @get('/{site_id}')
    @db_context_session
    async def get_site(self, site_id: str, session: DBAsyncScopedSession) -> SiteOut:
        scope = await current_scope()
        return await svc.site_out(session, scope, await access.load_site(session, scope, site_id))

    @patch('/{site_id}', summary='Name, slug, root site, locale, settings, home / 404 page')
    @db_context_session(auto_commit=True)
    async def update_site(self, site_id: str, data: SiteUpdate, session: DBAsyncScopedSession) -> SiteOut:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE.value, 'update')
        return await svc.site_out(session, scope, await svc.update_site(session, scope, site, data))

    @post('/{site_id}/archive', summary='Archive: taken off the public hosts, kept for restore')
    @db_context_session(auto_commit=True)
    async def archive(self, site_id: str, session: DBAsyncScopedSession) -> SiteOut:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE.value, 'update')
        return await svc.site_out(session, scope, await svc.set_status(session, scope, site, 'archived'))

    @post('/{site_id}/restore')
    @db_context_session(auto_commit=True)
    async def restore(self, site_id: str, session: DBAsyncScopedSession) -> SiteOut:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE.value, 'update')
        return await svc.site_out(session, scope, await svc.set_status(session, scope, site, 'active'))

    @delete('/{site_id}', status_code=status.HTTP_204_NO_CONTENT)
    @db_context_session(auto_commit=True)
    async def delete_site(self, site_id: str, session: DBAsyncScopedSession) -> None:
        scope = await current_scope()
        await svc.delete_site(session, scope, await access.load_site(session, scope, site_id, R.SITE.value, 'delete'))

    @put('/{site_id}/theme', summary='Design tokens, header and footer (contrast issues returned)')
    @db_context_session(auto_commit=True)
    async def set_theme(self, site_id: str, data: ThemeUpdate, session: DBAsyncScopedSession) -> ThemeOut:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE_THEME.value, 'update')
        theme, issues = await svc.set_theme(session, scope, site, data.theme)
        return ThemeOut(theme=theme, issues=issues)

    @get('/{site_id}/export', summary='Export the site (JSON; the editor adds Markdown + media)')
    @db_context_session
    async def export_site(self, site_id: str, session: DBAsyncScopedSession) -> SiteExportOut:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE_PAGE.value, 'read')
        return SiteExportOut(**await svc.export_site(session, site))

    @get('/{site_id}/audit', summary='Change history of the site (Site-0003)')
    @db_context_session
    async def audit_log(self, site_id: str, session: DBAsyncScopedSession, limit: int = 100) -> list[AuditOut]:
        from db.models.sites import SiteAudit

        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE.value, 'update')
        rows = list(
            await session.scalars(
                select(SiteAudit).where(SiteAudit.site_id == site.id).order_by(SiteAudit.created_at.desc()).limit(min(limit, 500))
            )
        )
        names = await svc.user_names(session, [r.actor_id for r in rows])
        return [
            AuditOut(
                id=str(r.id), action=r.action, actor_id=str(r.actor_id) if r.actor_id else None,
                actor_name=names.get(r.actor_id) if r.actor_id else None, target_type=r.target_type,
                target_id=r.target_id, source=r.source, detail=r.detail or {}, created_at=r.created_at,
            )
            for r in rows
        ]

    # --- members ----------------------------------------------------------------------------------

    @get('/{site_id}/members')
    @db_context_session
    async def list_members(self, site_id: str, session: DBAsyncScopedSession) -> list[MemberOut]:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE_MEMBER.value, 'read')
        return await members.list_members(session, scope, site)

    @get('/{site_id}/member-candidates', summary='Organization members that can be added')
    @db_context_session
    async def member_candidates(self, site_id: str, session: DBAsyncScopedSession, q: str | None = None) -> list[CandidateOut]:
        scope = await current_scope()
        await access.load_site(session, scope, site_id, R.SITE_MEMBER.value, 'manage')
        return await members.candidates(session, scope, q)

    @put('/{site_id}/members', summary='Grant or change the role of a user on the site')
    @db_context_session(auto_commit=True)
    async def upsert_member(self, site_id: str, data: MemberUpsert, session: DBAsyncScopedSession) -> MemberOut:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE_MEMBER.value, 'manage')
        return await members.upsert_member(session, scope, site, data.user_id, data.role)

    @delete('/{site_id}/members/{user_id}', status_code=status.HTTP_204_NO_CONTENT)
    @db_context_session(auto_commit=True)
    async def remove_member(self, site_id: str, user_id: str, session: DBAsyncScopedSession) -> None:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE_MEMBER.value, 'manage')
        await members.remove_member(session, scope, site, user_id)
