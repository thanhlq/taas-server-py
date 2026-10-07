"""``/api/v1/sites/{site_id}/pages`` (tree, drafts, revisions, soft lock), menus and redirects."""

from __future__ import annotations

from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.http import BaseController, delete, get, patch, post, put, status

from ews.authz import EwsResources
from ews.security import current_scope

from .. import _access as access
from .. import _service as svc
from .._document import validate_document
from ..schemas import (
    DocumentIn,
    DraftOut,
    DraftSave,
    LockOut,
    LockRequest,
    MenuOut,
    MenuUpdate,
    PageCreate,
    PageDetailOut,
    PageOut,
    PageUpdate,
    RedirectCreate,
    RedirectOut,
    RevisionDetailOut,
    RevisionOut,
    ValidationOut,
)

R = EwsResources


class SitePagesController(BaseController):
    api_prefix = '/api/v1/sites/{site_id}'
    tags = ('Site Builder',)

    @get('/pages', summary='Page tree (flat, ordered: parent_id + position)')
    @db_context_session
    async def list_pages(self, site_id: str, session: DBAsyncScopedSession) -> list[PageOut]:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE_PAGE.value, 'read')
        return await svc.list_pages(session, site)

    @post('/pages', status_code=status.HTTP_201_CREATED)
    @db_context_session(auto_commit=True)
    async def create_page(self, site_id: str, data: PageCreate, session: DBAsyncScopedSession) -> PageOut:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE_PAGE.value, 'create')
        return svc.page_out(site, await svc.create_page(session, scope, site, data))

    @post('/pages/validate', summary='Validate a document without saving (Markdown mode, imports)')
    async def validate(self, site_id: str, data: DocumentIn) -> ValidationOut:
        await current_scope()
        issues = [str(i) for i in validate_document(data.doc)]
        return ValidationOut(valid=not issues, issues=issues)

    @get('/pages/{page_id}', summary='Page with its draft document')
    @db_context_session
    async def get_page(self, site_id: str, page_id: str, session: DBAsyncScopedSession) -> PageDetailOut:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE_PAGE.value, 'read')
        return await svc.page_detail(session, site, await svc.get_page(session, site, page_id))

    @patch('/pages/{page_id}', summary='Title, slug (301 from the old path), parent, position, menu, SEO')
    @db_context_session(auto_commit=True)
    async def update_page(self, site_id: str, page_id: str, data: PageUpdate, session: DBAsyncScopedSession) -> PageOut:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE_PAGE.value, 'update')
        if data.seo is not None:
            await access.require(scope, site.id, R.SITE_SEO.value, 'update')
        page = await svc.update_page(session, scope, site, await svc.get_page(session, site, page_id), data)
        return svc.page_out(site, page)

    @delete('/pages/{page_id}', status_code=status.HTTP_204_NO_CONTENT, summary='Delete a page and its sub-pages')
    @db_context_session(auto_commit=True)
    async def delete_page(self, site_id: str, page_id: str, session: DBAsyncScopedSession) -> None:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE_PAGE.value, 'delete')
        await svc.delete_page(session, scope, site, await svc.get_page(session, site, page_id))

    @put('/pages/{page_id}/draft', summary='Autosave the draft document (validated, Site-0204)')
    @db_context_session(auto_commit=True)
    async def save_draft(self, site_id: str, page_id: str, data: DraftSave, session: DBAsyncScopedSession) -> DraftOut:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE_PAGE.value, 'update')
        if data.seo is not None:
            await access.require(scope, site.id, R.SITE_SEO.value, 'update')
        revision, created = await svc.save_draft(
            session, scope, site, await svc.get_page(session, site, page_id), data.doc, source=data.source,
            base_revision_id=data.base_revision_id, title=data.title, seo=data.seo, note=data.note,
        )
        return DraftOut(revision_id=str(revision.id), created_at=revision.created_at, new_revision=created)

    @get('/pages/{page_id}/revisions')
    @db_context_session
    async def list_revisions(self, site_id: str, page_id: str, session: DBAsyncScopedSession) -> list[RevisionOut]:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE_PAGE.value, 'read')
        return await svc.list_revisions(session, await svc.get_page(session, site, page_id))

    @get('/pages/{page_id}/revisions/{revision_id}')
    @db_context_session
    async def get_revision(self, site_id: str, page_id: str, revision_id: str, session: DBAsyncScopedSession) -> RevisionDetailOut:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE_PAGE.value, 'read')
        return await svc.get_revision(session, await svc.get_page(session, site, page_id), revision_id)

    @post('/pages/{page_id}/revisions/{revision_id}/restore', summary='Copy a revision into the draft (Site-0502)')
    @db_context_session(auto_commit=True)
    async def restore_revision(self, site_id: str, page_id: str, revision_id: str, session: DBAsyncScopedSession) -> DraftOut:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE_PAGE.value, 'update')
        revision = await svc.restore_revision(session, scope, site, await svc.get_page(session, site, page_id), revision_id)
        return DraftOut(revision_id=str(revision.id), created_at=revision.created_at, new_revision=True)

    @post('/pages/{page_id}/lock', summary='Take / refresh the soft lock (Site-0205); force = take over')
    @db_context_session(auto_commit=True)
    async def lock(self, site_id: str, page_id: str, data: LockRequest, session: DBAsyncScopedSession) -> LockOut:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE_PAGE.value, 'update')
        page = await svc.get_page(session, site, page_id)
        locked, holder = await svc.lock_page(session, scope, page, force=data.force)
        names = await svc.user_names(session, [holder])
        return LockOut(locked=locked, holder_id=str(holder) if holder else None, holder_name=names.get(holder) if holder else None, locked_at=page.locked_at)

    @delete('/pages/{page_id}/lock', status_code=status.HTTP_204_NO_CONTENT)
    @db_context_session(auto_commit=True)
    async def unlock(self, site_id: str, page_id: str, session: DBAsyncScopedSession) -> None:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE_PAGE.value, 'read')
        await svc.unlock_page(session, scope, await svc.get_page(session, site, page_id))

    # --- menus / redirects ------------------------------------------------------------------------

    @get('/menus')
    @db_context_session
    async def get_menus(self, site_id: str, session: DBAsyncScopedSession) -> list[MenuOut]:
        scope = await current_scope()
        return await svc.get_menus(session, await access.load_site(session, scope, site_id))

    @put('/menus/{key}', summary='Replace the header / footer menu (2 levels)')
    @db_context_session(auto_commit=True)
    async def set_menu(self, site_id: str, key: str, data: MenuUpdate, session: DBAsyncScopedSession) -> MenuOut:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE_MENU.value, 'update')
        return await svc.set_menu(session, scope, site, key, data.items)

    @get('/redirects')
    @db_context_session
    async def list_redirects(self, site_id: str, session: DBAsyncScopedSession) -> list[RedirectOut]:
        scope = await current_scope()
        return await svc.list_redirects(session, await access.load_site(session, scope, site_id))

    @post('/redirects', status_code=status.HTTP_201_CREATED)
    @db_context_session(auto_commit=True)
    async def create_redirect(self, site_id: str, data: RedirectCreate, session: DBAsyncScopedSession) -> RedirectOut:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE_REDIRECT.value, 'manage')
        return svc.redirect_out(await svc.create_redirect(session, scope, site, data.from_path, data.to, data.status_code))

    @delete('/redirects/{redirect_id}', status_code=status.HTTP_204_NO_CONTENT)
    @db_context_session(auto_commit=True)
    async def delete_redirect(self, site_id: str, redirect_id: str, session: DBAsyncScopedSession) -> None:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE_REDIRECT.value, 'manage')
        await svc.delete_redirect(session, scope, site, redirect_id)
