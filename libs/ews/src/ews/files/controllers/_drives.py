"""``/api/v1/files/drives`` — drives, members (generic ``ews.access`` routes), folder content, uploads, trash,
activity. Every handler: ``current_scope()`` then ``load_drive`` (404 unreadable / 403 missing right)."""

from __future__ import annotations

from typing import Literal

from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException
from foundation.http import BaseController, delete, get, patch, post, put, status
from foundation.http.context import Context

from ews.access import (
    CandidateOut,
    MemberOut,
    MemberUpsert,
    list_members,
    member_candidates,
    remove_member,
    upsert_member,
)
from ews.security import authorize, current_scope

from .. import _access as access
from .. import _activity as activity
from .. import _drives as drives
from .. import _nodes as nodes
from .. import _uploads as uploads
from ..schemas import (
    FileActivityOut,
    FileCountOut,
    FileDriveCreate,
    FileDriveOut,
    FileDriveUpdate,
    FileFolderCreate,
    FileNodeOut,
    FileNodePage,
    FileUploadOut,
    FileUploadRequest,
    FileUploadTicketOut,
)
from ._support import field, multipart_file, on_conflict

_Type = Literal['folder', 'file', 'document', 'image', 'video', 'audio', 'other']


def _no_personal_members(ctx: access.DriveCtx) -> None:
    if ctx.drive.kind == 'personal':
        raise ClientException(
            detail='My files has no members: share files and folders instead (F2)'
        )
    if ctx.drive.kind == 'project':
        raise ClientException(
            detail="a project's files belong to the project: manage its members in the project"
        )


class FilesDrivesController(BaseController):
    api_prefix = '/api/v1/files/drives'
    tags = ('File Manager',)

    @get(
        '/',
        summary='Drives the caller can read (organization drive, shared drives, shared with me, My files)',
    )
    @db_context_session(auto_commit=True)
    async def list_drives(self, session: DBAsyncScopedSession) -> list[FileDriveOut]:
        scope = await current_scope()
        return await drives.drive_outputs(
            session, scope, await drives.visible_drives(session, scope)
        )

    @post(
        '/',
        status_code=status.HTTP_201_CREATED,
        summary='Create a shared drive (the creator becomes Drive Manager)',
    )
    @db_context_session(auto_commit=True)
    async def create_drive(
        self, data: FileDriveCreate, session: DBAsyncScopedSession
    ) -> FileDriveOut:
        scope = await current_scope()
        await authorize(scope, access.DRIVE, 'create')
        ctx = await drives.create_shared_drive(session, scope, data)
        return (await drives.drive_outputs(session, scope, [ctx]))[0]

    @get('/{drive_id}')
    @db_context_session(auto_commit=True)
    async def get_drive(
        self, drive_id: str, session: DBAsyncScopedSession
    ) -> FileDriveOut:
        scope = await current_scope()
        ctx = await access.load_drive(session, scope, drive_id)
        await access.log_oversight(session, scope, ctx, 'drive')
        return (await drives.drive_outputs(session, scope, [ctx]))[0]

    @patch(
        '/{drive_id}',
        summary="Name, description, color, sensitivity, default role of the organization's members",
    )
    @db_context_session(auto_commit=True)
    async def update_drive(
        self, drive_id: str, data: FileDriveUpdate, session: DBAsyncScopedSession
    ) -> FileDriveOut:
        scope = await current_scope()
        ctx = await access.load_drive(session, scope, drive_id, access.DRIVE, 'update')
        await drives.update_drive(session, scope, ctx, data)
        return (await drives.drive_outputs(session, scope, [ctx]))[0]

    @post(
        '/{drive_id}/links/revoke',
        status_code=status.HTTP_204_NO_CONTENT,
        summary='Revoke every signed URL of the drive handed out so far (thumbnails, previews, downloads)',
    )
    @db_context_session(auto_commit=True)
    async def revoke_links(self, drive_id: str, session: DBAsyncScopedSession) -> None:
        scope = await current_scope()
        ctx = await access.load_drive(session, scope, drive_id, access.DRIVE, 'update')
        await drives.revoke_drive_links(session, scope, ctx)

    @delete(
        '/{drive_id}',
        status_code=status.HTTP_204_NO_CONTENT,
        summary='Delete a shared drive',
    )
    @db_context_session(auto_commit=True)
    async def delete_drive(self, drive_id: str, session: DBAsyncScopedSession) -> None:
        scope = await current_scope()
        ctx = await access.load_drive(session, scope, drive_id, access.DRIVE, 'delete')
        await drives.delete_drive(session, scope, ctx)

    # --- members ----------------------------------------------------------------------------------

    @get(
        '/{drive_id}/members',
        summary='Direct members (highest role first) + inherited admins',
    )
    @db_context_session
    async def list_members(
        self, drive_id: str, session: DBAsyncScopedSession
    ) -> list[MemberOut]:
        scope = await current_scope()
        ctx = await access.load_drive(session, scope, drive_id, access.MEMBER, 'read')
        org_domains = access.DRIVES.domains(scope, ctx.drive.id, org_path=ctx.org_path)[
            1:
        ]
        return await list_members(
            session, scope, access.DRIVES, ctx.drive.id, org_domains=org_domains
        )

    @get(
        '/{drive_id}/member-candidates',
        summary='Members of the organization that can be added',
    )
    @db_context_session
    async def member_candidates(
        self, drive_id: str, session: DBAsyncScopedSession, q: str | None = None
    ) -> list[CandidateOut]:
        scope = await current_scope()
        _no_personal_members(
            await access.load_drive(session, scope, drive_id, access.MEMBER, 'manage')
        )
        return await member_candidates(session, scope, q)

    @put(
        '/{drive_id}/members', summary='Grant or change the role of a user on the drive'
    )
    @db_context_session(auto_commit=True)
    async def upsert_member(
        self, drive_id: str, data: MemberUpsert, session: DBAsyncScopedSession
    ) -> MemberOut:
        scope = await current_scope()
        ctx = await access.load_drive(session, scope, drive_id, access.MEMBER, 'manage')
        _no_personal_members(ctx)
        member = await upsert_member(
            session, scope, access.DRIVES, ctx.drive.id, data.user_id, data.role
        )
        activity.record(
            session,
            scope,
            ctx.drive.id,
            'member.granted',
            user_id=member.user_id,
            role=member.role,
        )
        return member

    @delete('/{drive_id}/members/{user_id}', status_code=status.HTTP_204_NO_CONTENT)
    @db_context_session(auto_commit=True)
    async def remove_member(
        self, drive_id: str, user_id: str, session: DBAsyncScopedSession
    ) -> None:
        scope = await current_scope()
        ctx = await access.load_drive(session, scope, drive_id, access.MEMBER, 'manage')
        _no_personal_members(ctx)
        await remove_member(session, scope, access.DRIVES, ctx.drive.id, user_id)
        activity.record(session, scope, ctx.drive.id, 'member.revoked', user_id=user_id)
        # The removed member may hold 24 h view URLs: they stop working.
        await drives.revoke_drive_links(session, scope, ctx, reason='member_removed')

    # --- content ----------------------------------------------------------------------------------

    @get(
        '/{drive_id}/nodes',
        summary='Folders and files of a folder (folders first; parent_id empty = top level; q = name contains)',
    )
    @db_context_session(auto_commit=True)
    async def list_nodes(
        self,
        drive_id: str,
        session: DBAsyncScopedSession,
        parent_id: str | None = None,
        type: _Type | None = None,  # noqa: A002 — public query name
        q: str | None = None,
        sort: Literal['name', 'updated', 'size', 'created'] = 'name',
        order: Literal['asc', 'desc'] = 'asc',
        limit: int = 200,
        offset: int = 0,
    ) -> FileNodePage:
        scope = await current_scope()
        ctx = await access.load_drive(session, scope, drive_id, access.ITEM, 'read')
        parent = await nodes.get_folder(session, ctx.drive.id, parent_id)
        rows, total = await nodes.list_children(
            session,
            ctx,
            parent,
            file_type_=type,
            q=q,
            sort=sort,
            order=order,
            limit=limit,
            offset=offset,
        )
        await access.log_oversight(session, scope, ctx, 'list')
        return FileNodePage(
            items=await nodes.node_outputs(session, scope, rows),
            total=total,
            limit=limit,
            offset=offset,
        )

    @post('/{drive_id}/folders', status_code=status.HTTP_201_CREATED)
    @db_context_session(auto_commit=True)
    async def create_folder(
        self, drive_id: str, data: FileFolderCreate, session: DBAsyncScopedSession
    ) -> FileNodeOut:
        scope = await current_scope()
        ctx = await access.load_drive(session, scope, drive_id, access.ITEM, 'create')
        return await nodes.node_output(
            session, scope, await nodes.create_folder(session, scope, ctx, data)
        )

    @post(
        '/{drive_id}/files',
        status_code=status.HTTP_201_CREATED,
        summary='Upload a file through the API (multipart "file"; parent_id, relative_path, on_conflict, comment)',
    )
    @db_context_session(auto_commit=True)
    async def upload(
        self, drive_id: str, ctx: Context, session: DBAsyncScopedSession
    ) -> FileUploadOut:
        scope = await current_scope()
        drive = await access.load_drive(session, scope, drive_id, access.ITEM, 'create')
        data, filename, form = await multipart_file(ctx)
        result, node = await uploads.upload_file(
            session,
            scope,
            drive,
            data,
            field(form, 'name') or filename,
            parent_id=field(form, 'parent_id'),
            relative_path=field(form, 'relative_path'),
            on_conflict=on_conflict(form),  # type: ignore[arg-type]
            comment=field(form, 'comment'),
            declared_mime=getattr(form.get('file'), 'content_type', None),
        )
        return FileUploadOut(
            result=result, node=await nodes.node_output(session, scope, node)
        )

    @post(
        '/{drive_id}/uploads',
        summary='Ticket of a direct upload: PUT the bytes to url, then POST /uploads/complete',
    )
    @db_context_session(auto_commit=True)
    async def upload_ticket(
        self, drive_id: str, data: FileUploadRequest, session: DBAsyncScopedSession
    ) -> FileUploadTicketOut:
        scope = await current_scope()
        return await uploads.upload_ticket(session, scope, drive_id, data)

    # --- trash & activity -------------------------------------------------------------------------

    @get(
        '/{drive_id}/trash',
        summary='Items deleted to the trash (restore: Editors / Managers)',
    )
    @db_context_session
    async def list_trash(
        self,
        drive_id: str,
        session: DBAsyncScopedSession,
        limit: int = 200,
        offset: int = 0,
    ) -> FileNodePage:
        scope = await current_scope()
        ctx = await access.load_drive(session, scope, drive_id, access.ITEM, 'restore')
        rows, total = await nodes.list_trash(session, ctx, limit, offset)
        return FileNodePage(
            items=await nodes.node_outputs(session, scope, rows),
            total=total,
            limit=limit,
            offset=offset,
        )

    @delete('/{drive_id}/trash', summary='Empty the trash (delete for good: Managers)')
    @db_context_session(auto_commit=True)
    async def empty_trash(
        self, drive_id: str, session: DBAsyncScopedSession
    ) -> FileCountOut:
        scope = await current_scope()
        ctx = await access.load_drive(session, scope, drive_id, access.DRIVE, 'delete')
        return FileCountOut(count=await nodes.empty_trash(session, scope, ctx))

    @get(
        '/{drive_id}/activity',
        summary='Activity of the drive, newest first (File-0307)',
    )
    @db_context_session
    async def drive_activity(
        self, drive_id: str, session: DBAsyncScopedSession, limit: int = 100
    ) -> list[FileActivityOut]:
        scope = await current_scope()
        ctx = await access.load_drive(session, scope, drive_id)
        return await activity.list_activity(
            session, scope, drive_id=ctx.drive.id, limit=limit
        )
