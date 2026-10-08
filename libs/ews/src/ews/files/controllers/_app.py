"""``/api/v1/files`` — app gate, roles, home / recent / starred / search, direct-upload completion and the
signed content / upload URLs (no session: the token is the authorization)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import NotFoundException
from foundation.http import BaseController, get, post, put, status
from foundation.http.context import Context

from ews.access import RoleOut, object_roles
from ews.security import current_scope, is_allowed
from ews.shared import raw_response

from .. import _access as access
from .. import _drives as drives
from .. import _nodes as nodes
from .. import _storage as storage
from .. import _uploads as uploads
from .. import _views as views
from .._settings import files_settings
from ..schemas import (
    FilesAccessOut,
    FilesHomeOut,
    FileNodeOut,
    FileNodePage,
    FileUploadComplete,
    FileUploadOut,
)


class FilesAppController(BaseController):
    api_prefix = '/api/v1/files'
    tags = ('File Manager',)

    @get(
        '/access',
        summary='Can the caller open the File Manager? (creates the organization drive and My files)',
    )
    @db_context_session(auto_commit=True)
    async def access(self, session: DBAsyncScopedSession) -> FilesAccessOut:
        scope = await current_scope()
        org_drive = await drives.ensure_organization_drive(session, scope)
        personal = await drives.ensure_personal_drive(session, scope)
        org_ctx = await access.drive_ctx(session, scope, org_drive)
        settings = files_settings()
        return FilesAccessOut(
            allowed=True,
            can_create_shared_drive=await is_allowed(
                scope, access.DRIVE, 'create', scope.org_domains()
            ),
            organization_drive_id=str(org_drive.id)
            if await access.allowed(scope, org_ctx, access.DRIVE, 'read')
            else None,
            personal_drive_id=str(personal.id),
            organization_slug=scope.organization.slug,
            max_upload_bytes=settings.max_upload_bytes,
            delivery=settings.delivery,
        )

    @get('/roles', summary='Roles that can be granted on a drive (highest first)')
    async def list_roles(self) -> list[RoleOut]:
        await current_scope()
        return object_roles(access.DRIVES)

    @get('/home', summary='Drives the caller can read + its recent files')
    @db_context_session(auto_commit=True)
    async def home(self, session: DBAsyncScopedSession) -> FilesHomeOut:
        scope = await current_scope()
        return await views.home(session, scope)

    @get(
        '/recent',
        summary="Recent files (last change or the caller's last action), readable drives only",
    )
    @db_context_session(auto_commit=True)
    async def recent(
        self, session: DBAsyncScopedSession, limit: int = 30
    ) -> list[FileNodeOut]:
        scope = await current_scope()
        return await views.recent(
            session, scope, await drives.visible_drives(session, scope), limit
        )

    @get('/starred', summary='Items the caller starred, readable drives only')
    @db_context_session(auto_commit=True)
    async def starred(self, session: DBAsyncScopedSession) -> list[FileNodeOut]:
        scope = await current_scope()
        return await views.starred(
            session, scope, await drives.visible_drives(session, scope)
        )

    @get(
        '/search',
        summary='Search folders and files by name, type, owner, date (File-0400 metadata)',
    )
    @db_context_session(auto_commit=True)
    async def search(
        self,
        session: DBAsyncScopedSession,
        q: str | None = None,
        type: Literal['folder', 'file', 'document', 'image', 'video', 'audio', 'other']
        | None = None,  # noqa: A002
        drive_id: str | None = None,
        owner: str | None = None,
        modified_after: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> FileNodePage:
        scope = await current_scope()
        ctxs = await drives.visible_drives(session, scope)
        return await views.search(
            session,
            scope,
            ctxs,
            q=q,
            file_type_=type,
            drive_id=drive_id,
            owner=owner,
            modified_after=modified_after,
            limit=limit,
            offset=offset,
        )

    @post(
        '/uploads/complete',
        status_code=status.HTTP_201_CREATED,
        summary='Register a direct upload',
    )
    @db_context_session(auto_commit=True)
    async def complete_upload(
        self, data: FileUploadComplete, session: DBAsyncScopedSession
    ) -> FileUploadOut:
        scope = await current_scope()
        result, node = await uploads.complete_upload(
            session, scope, data.token, data.comment
        )
        return FileUploadOut(
            result=result, node=await nodes.node_output(session, scope, node)
        )

    @put(
        '/uploads/{token}',
        status_code=status.HTTP_204_NO_CONTENT,
        summary='Bytes of a direct upload (proxy delivery; signed URL)',
    )
    async def receive_upload(self, token: str, ctx: Context) -> None:
        await uploads.receive_upload(
            token, await ctx.req.body(), ctx.req.headers.get('content-length')
        )

    @get(
        '/content/{token}',
        summary='File bytes behind a signed download / preview URL (no session needed)',
    )
    async def content(self, token: str, ctx: Context) -> Any:
        claims = storage.read_content_token(token)
        if claims is None:
            raise NotFoundException(detail='link expired or invalid')
        blob = await (await storage.store_for(claims['t'])).get(claims['k'])
        if blob is None:
            raise NotFoundException(detail='file not found')
        mime: str = claims['m'] or 'application/octet-stream'
        headers = storage.content_headers(
            mime, claims['f'], inline=bool(claims.get('i')), etag=blob.info.etag
        )
        return raw_response(
            blob.body, media_type=mime, headers=headers, request=ctx.req
        )
