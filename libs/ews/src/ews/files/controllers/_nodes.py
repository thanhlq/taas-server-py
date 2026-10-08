"""``/api/v1/files/nodes`` — one folder / file: details, rename, move, copy, star, trash / restore / purge,
versions, download / preview, activity. Every handler: ``current_scope()`` then ``load_node`` (404 / 403)."""

from __future__ import annotations

from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException
from foundation.http import BaseController, delete, get, patch, post, put, status
from foundation.http.context import Context

from ews.security import current_scope

from .. import _access as access
from .. import _activity as activity
from .. import _nodes as nodes
from .. import _uploads as uploads
from ..schemas import (
    FileActivityOut,
    FileDownloadOut,
    FileNodeCopy,
    FileNodeDetailOut,
    FileNodeMove,
    FileNodeOut,
    FileNodeUpdate,
    FileVersionOut,
    FileVersionUpdate,
)
from ._support import field, multipart_file


class FilesNodesController(BaseController):
    api_prefix = '/api/v1/files/nodes'
    tags = ('File Manager',)

    @get(
        '/{node_id}',
        summary="Folder / file with breadcrumb and the caller's permissions (trashed items too)",
    )
    @db_context_session
    async def get_node(
        self, node_id: str, session: DBAsyncScopedSession
    ) -> FileNodeDetailOut:
        scope = await current_scope()
        node, ctx = await access.load_node(session, scope, node_id, trashed=None)
        return await nodes.node_detail(session, scope, node, ctx)

    @patch('/{node_id}', summary='Rename and / or color')
    @db_context_session(auto_commit=True)
    async def update_node(
        self, node_id: str, data: FileNodeUpdate, session: DBAsyncScopedSession
    ) -> FileNodeOut:
        scope = await current_scope()
        node, ctx = await access.load_node(
            session, scope, node_id, access.ITEM, 'update'
        )
        await nodes.update_node(session, scope, ctx, node, data)
        return await nodes.node_output(session, scope, node)

    @post(
        '/{node_id}/move', summary='Move inside the drive (parent_id null = top level)'
    )
    @db_context_session(auto_commit=True)
    async def move_node(
        self, node_id: str, data: FileNodeMove, session: DBAsyncScopedSession
    ) -> FileNodeOut:
        scope = await current_scope()
        node, ctx = await access.load_node(
            session, scope, node_id, access.ITEM, 'update'
        )
        await nodes.move_node(session, scope, ctx, node, data.parent_id)
        return await nodes.node_output(session, scope, node)

    @post(
        '/{node_id}/copy',
        status_code=status.HTTP_201_CREATED,
        summary='Copy a file in the same drive',
    )
    @db_context_session(auto_commit=True)
    async def copy_node(
        self, node_id: str, data: FileNodeCopy, session: DBAsyncScopedSession
    ) -> FileNodeOut:
        scope = await current_scope()
        node, ctx = await access.load_node(session, scope, node_id, access.ITEM, 'read')
        await access.check(scope, ctx, access.ITEM, 'create', what='item')
        return await nodes.node_output(
            session, scope, await nodes.copy_file(session, scope, ctx, node, data)
        )

    @delete(
        '/{node_id}',
        status_code=status.HTTP_204_NO_CONTENT,
        summary='Move to the trash with its subtree; permanent=true deletes a trashed item for good (Managers)',
    )
    @db_context_session(auto_commit=True)
    async def delete_node(
        self, node_id: str, session: DBAsyncScopedSession, permanent: bool = False
    ) -> None:
        scope = await current_scope()
        if not permanent:
            node, ctx = await access.load_node(
                session, scope, node_id, access.ITEM, 'delete'
            )
            await nodes.trash_node(session, scope, ctx, node)
            return
        node, ctx = await access.load_node(
            session, scope, node_id, access.DRIVE, 'delete', trashed=True
        )
        if node.trash_root_id != node.id:
            raise ClientException(
                detail='delete the folder this item was trashed with',
                extra={'code': 'not_trash_root'},
            )
        await nodes.purge_subtree(session, scope, node)

    @post('/{node_id}/restore', summary='Restore from the trash (Editors / Managers)')
    @db_context_session(auto_commit=True)
    async def restore_node(
        self, node_id: str, session: DBAsyncScopedSession
    ) -> FileNodeOut:
        scope = await current_scope()
        node, ctx = await access.load_node(
            session, scope, node_id, access.ITEM, 'restore', trashed=True
        )
        await nodes.restore_node(session, scope, ctx, node)
        return await nodes.node_output(session, scope, node)

    @put('/{node_id}/star', status_code=status.HTTP_204_NO_CONTENT)
    @db_context_session(auto_commit=True)
    async def star(self, node_id: str, session: DBAsyncScopedSession) -> None:
        scope = await current_scope()
        node, _ = await access.load_node(session, scope, node_id)
        await nodes.set_star(session, scope, node, True)

    @delete('/{node_id}/star', status_code=status.HTTP_204_NO_CONTENT)
    @db_context_session(auto_commit=True)
    async def unstar(self, node_id: str, session: DBAsyncScopedSession) -> None:
        scope = await current_scope()
        node, _ = await access.load_node(session, scope, node_id, trashed=None)
        await nodes.set_star(session, scope, node, False)

    # --- versions & content -----------------------------------------------------------------------

    @get('/{node_id}/versions', summary='Versions of a file, newest first')
    @db_context_session
    async def list_versions(
        self, node_id: str, session: DBAsyncScopedSession
    ) -> list[FileVersionOut]:
        scope = await current_scope()
        node, _ = await access.load_node(session, scope, node_id)
        return await uploads.list_versions(session, node)

    @post(
        '/{node_id}/versions',
        status_code=status.HTTP_201_CREATED,
        summary='Upload a new version (multipart "file", comment)',
    )
    @db_context_session(auto_commit=True)
    async def upload_version(
        self, node_id: str, ctx: Context, session: DBAsyncScopedSession
    ) -> FileNodeOut:
        scope = await current_scope()
        node, drive = await access.load_node(
            session, scope, node_id, access.ITEM, 'update'
        )
        data, _, form = await multipart_file(ctx)
        node = await uploads.upload_version(
            session, scope, drive, node, data, comment=field(form, 'comment')
        )
        return await nodes.node_output(session, scope, node)

    @post(
        '/{node_id}/versions/{version_id}/restore',
        summary='Make an old version current again (as a new version)',
    )
    @db_context_session(auto_commit=True)
    async def restore_version(
        self, node_id: str, version_id: str, session: DBAsyncScopedSession
    ) -> FileNodeOut:
        scope = await current_scope()
        node, ctx = await access.load_node(
            session, scope, node_id, access.ITEM, 'update'
        )
        return await nodes.node_output(
            session,
            scope,
            await uploads.restore_version(session, scope, ctx, node, version_id),
        )

    @patch('/{node_id}/versions/{version_id}', summary='Version comment')
    @db_context_session(auto_commit=True)
    async def update_version(
        self,
        node_id: str,
        version_id: str,
        data: FileVersionUpdate,
        session: DBAsyncScopedSession,
    ) -> FileVersionOut:
        scope = await current_scope()
        node, ctx = await access.load_node(
            session, scope, node_id, access.ITEM, 'update'
        )
        return await uploads.comment_version(
            session, scope, ctx, node, version_id, data.comment
        )

    @get(
        '/{node_id}/download',
        summary='Signed URL (1–5 min) to download or preview (inline: safe types only)',
    )
    @db_context_session(auto_commit=True)
    async def download(
        self,
        node_id: str,
        session: DBAsyncScopedSession,
        version_id: str | None = None,
        inline: bool = False,
    ) -> FileDownloadOut:
        scope = await current_scope()
        node, ctx = await access.load_node(session, scope, node_id)
        return await uploads.download(
            session, scope, ctx, node, version_id=version_id, inline=inline
        )

    @get(
        '/{node_id}/activity',
        summary='Activity of the item (a folder: with its subtree)',
    )
    @db_context_session
    async def node_activity(
        self, node_id: str, session: DBAsyncScopedSession, limit: int = 100
    ) -> list[FileActivityOut]:
        scope = await current_scope()
        node, ctx = await access.load_node(session, scope, node_id, trashed=None)
        return await activity.list_activity(
            session, scope, drive_id=ctx.drive.id, node=node, limit=limit
        )
