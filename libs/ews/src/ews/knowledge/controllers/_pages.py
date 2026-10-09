"""``/api/v1/knowledge/pages/{page_id}`` — read, settings, move, delete, draft / publish / versions, soft lock,
verification and attachments. Every route loads the page through ``_access.load_page`` (404 / 403, drafts hidden
from readers)."""

from __future__ import annotations

from typing import Literal

from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException
from foundation.exceptions.http_exceptions import RequestEntityTooLarge
from foundation.http import BaseController, delete, get, patch, post, put, status
from foundation.http.context import Context

from ews.security import current_scope
from ews.shared import read_form, user_names

from .. import _attachments, _pages, _revisions
from .._access import PAGE, load_page
from .._rules import MAX_ATTACHMENT_BYTES
from ..schemas import (
    KbAttachmentOut,
    KbDownloadOut,
    KbDraftOut,
    KbDraftSave,
    KbLockOut,
    KbLockRequest,
    KbPageDetailOut,
    KbPageMove,
    KbPageOut,
    KbPageUpdate,
    KbPublishRequest,
    KbRevisionDetailOut,
    KbRevisionOut,
)


async def _upload_file(ctx: Context) -> tuple[bytes, str | None, str | None]:
    length = ctx.req.headers.get('content-length')
    if length and length.isdigit() and int(length) > MAX_ATTACHMENT_BYTES + 64 * 1024:
        raise RequestEntityTooLarge(detail='file too large')
    form = await read_form(ctx.req)
    upload = form.get('file')
    if upload is None or not hasattr(upload, 'read'):
        raise ClientException(detail='multipart field "file" is required')
    return (
        await upload.read(),
        getattr(upload, 'filename', None),
        getattr(upload, 'content_type', None),
    )


class KnowledgePagesController(BaseController):
    api_prefix = '/api/v1/knowledge/pages'
    tags = ('Knowledge Center',)

    @get(
        '/{page_id}',
        summary='Page with its document: draft for editors, published version for readers',
    )
    @db_context_session
    async def get_page(
        self,
        page_id: str,
        session: DBAsyncScopedSession,
        view: Literal['draft', 'published'] | None = None,
    ) -> KbPageDetailOut:
        scope = await current_scope()
        return await _pages.page_detail(
            session, scope, await load_page(session, scope, page_id), view
        )

    @patch(
        '/{page_id}',
        summary='Slug, owner, review interval (title and body: PUT /draft)',
    )
    @db_context_session(auto_commit=True)
    async def update_page(
        self, page_id: str, data: KbPageUpdate, session: DBAsyncScopedSession
    ) -> KbPageOut:
        scope = await current_scope()
        pa = await load_page(session, scope, page_id, PAGE, 'update')
        page = await _pages.update_page(session, scope, pa, data)
        return _pages.page_out(
            page, scope, editor=True, names=await user_names(session, [page.owner_id])
        )

    @post(
        '/{page_id}/move',
        summary='Move under another page of the space and / or reorder (≤ 10 levels)',
    )
    @db_context_session(auto_commit=True)
    async def move_page(
        self, page_id: str, data: KbPageMove, session: DBAsyncScopedSession
    ) -> KbPageOut:
        scope = await current_scope()
        pa = await load_page(session, scope, page_id, PAGE, 'update')
        return _pages.page_out(
            await _pages.move_page(session, scope, pa, data),
            scope,
            editor=True,
            names={},
        )

    @delete(
        '/{page_id}',
        status_code=status.HTTP_204_NO_CONTENT,
        summary='Delete the page and its sub-pages (soft)',
    )
    @db_context_session(auto_commit=True)
    async def delete_page(self, page_id: str, session: DBAsyncScopedSession) -> None:
        scope = await current_scope()
        await _pages.delete_page(
            session, scope, await load_page(session, scope, page_id, PAGE, 'delete')
        )

    # --- draft / publish / versions -----------------------------------------------------------------

    @put(
        '/{page_id}/draft',
        summary='Autosave title and / or body of the draft (validated site document)',
    )
    @db_context_session(auto_commit=True)
    async def save_draft(
        self, page_id: str, data: KbDraftSave, session: DBAsyncScopedSession
    ) -> KbDraftOut:
        scope = await current_scope()
        return await _revisions.save_draft(
            session,
            scope,
            await load_page(session, scope, page_id, PAGE, 'update'),
            data,
        )

    @post(
        '/{page_id}/publish',
        summary='Publish the draft as a new version (readers see it)',
    )
    @db_context_session(auto_commit=True)
    async def publish(
        self, page_id: str, data: KbPublishRequest, session: DBAsyncScopedSession
    ) -> KbPageOut:
        scope = await current_scope()
        pa = await load_page(session, scope, page_id, PAGE, 'publish')
        page = await _revisions.publish(session, scope, pa, data.note)
        return _pages.page_out(
            page, scope, editor=True, names=await user_names(session, [page.owner_id])
        )

    @post(
        '/{page_id}/draft/discard',
        summary='Discard the unpublished changes: the draft goes back to the published version',
    )
    @db_context_session(auto_commit=True)
    async def discard_draft(self, page_id: str, session: DBAsyncScopedSession) -> KbDraftOut:
        scope = await current_scope()
        return await _revisions.discard_draft(
            session, scope, await load_page(session, scope, page_id, PAGE, 'update')
        )

    @get(
        '/{page_id}/revisions',
        summary='Versions and drafts, newest first (editors; diff in the web)',
    )
    @db_context_session
    async def list_revisions(
        self, page_id: str, session: DBAsyncScopedSession
    ) -> list[KbRevisionOut]:
        scope = await current_scope()
        return await _revisions.list_revisions(
            session, (await load_page(session, scope, page_id, PAGE, 'update')).page
        )

    @get('/{page_id}/revisions/{revision_id}')
    @db_context_session
    async def get_revision(
        self, page_id: str, revision_id: str, session: DBAsyncScopedSession
    ) -> KbRevisionDetailOut:
        scope = await current_scope()
        page = (await load_page(session, scope, page_id, PAGE, 'update')).page
        return await _revisions.get_revision(session, page, revision_id)

    @post(
        '/{page_id}/revisions/{revision_id}/restore',
        summary='Copy a version into a new draft',
    )
    @db_context_session(auto_commit=True)
    async def restore_revision(
        self, page_id: str, revision_id: str, session: DBAsyncScopedSession
    ) -> KbDraftOut:
        scope = await current_scope()
        pa = await load_page(session, scope, page_id, PAGE, 'update')
        return await _revisions.restore_revision(session, scope, pa, revision_id)

    # --- soft lock / verification -------------------------------------------------------------------

    @post(
        '/{page_id}/lock',
        summary='Take / refresh the soft lock while editing; force = take over',
    )
    @db_context_session(auto_commit=True)
    async def lock(
        self, page_id: str, data: KbLockRequest, session: DBAsyncScopedSession
    ) -> KbLockOut:
        scope = await current_scope()
        pa = await load_page(session, scope, page_id, PAGE, 'update')
        return await _revisions.lock(session, scope, pa.page, force=data.force)

    @delete(
        '/{page_id}/lock',
        status_code=status.HTTP_204_NO_CONTENT,
        summary='Release the soft lock',
    )
    @db_context_session(auto_commit=True)
    async def unlock(self, page_id: str, session: DBAsyncScopedSession) -> None:
        scope = await current_scope()
        await _revisions.unlock(
            session,
            scope,
            (await load_page(session, scope, page_id, PAGE, 'update')).page,
        )

    @post(
        '/{page_id}/verify',
        summary='Verify the published content (verified until now + review interval)',
    )
    @db_context_session(auto_commit=True)
    async def verify(self, page_id: str, session: DBAsyncScopedSession) -> KbPageOut:
        scope = await current_scope()
        pa = await load_page(session, scope, page_id, PAGE, 'verify')
        page = await _revisions.verify(session, scope, pa)
        return _pages.page_out(
            page, scope, editor=True, names=await user_names(session, [page.owner_id])
        )

    # --- attachments --------------------------------------------------------------------------------

    @get('/{page_id}/attachments')
    @db_context_session
    async def list_attachments(
        self, page_id: str, session: DBAsyncScopedSession
    ) -> list[KbAttachmentOut]:
        scope = await current_scope()
        return await _attachments.list_attachments(
            session, await load_page(session, scope, page_id)
        )

    @post(
        '/{page_id}/attachments',
        status_code=status.HTTP_201_CREATED,
        summary='Upload an attachment (multipart "file", ≤ 50 MB)',
    )
    @db_context_session(auto_commit=True)
    async def upload_attachment(
        self, page_id: str, ctx: Context, session: DBAsyncScopedSession
    ) -> KbAttachmentOut:
        scope = await current_scope()
        pa = await load_page(session, scope, page_id, PAGE, 'update')
        data, filename, content_type = await _upload_file(ctx)
        attachment = await _attachments.upload(
            session, scope, pa, data, filename, content_type
        )
        return _attachments.attachment_out(
            attachment, await user_names(session, [scope.user_id])
        )

    @delete(
        '/{page_id}/attachments/{attachment_id}', status_code=status.HTTP_204_NO_CONTENT
    )
    @db_context_session(auto_commit=True)
    async def delete_attachment(
        self, page_id: str, attachment_id: str, session: DBAsyncScopedSession
    ) -> None:
        scope = await current_scope()
        pa = await load_page(session, scope, page_id, PAGE, 'update')
        await _attachments.delete_attachment(
            session, await _attachments.get_attachment(session, pa, attachment_id)
        )

    @get(
        '/{page_id}/attachments/{attachment_id}/download',
        summary='Signed URL of an attachment (5 min)',
    )
    @db_context_session
    async def download_attachment(
        self,
        page_id: str,
        attachment_id: str,
        session: DBAsyncScopedSession,
        inline: bool = False,
    ) -> KbDownloadOut:
        scope = await current_scope()
        pa = await load_page(session, scope, page_id)
        return await _attachments.download_url(
            await _attachments.get_attachment(session, pa, attachment_id), inline=inline
        )
