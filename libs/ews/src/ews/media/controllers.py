"""``/api/v1/media`` — media library of the caller's organization (taas-specs/media/media-app-spec.md).

Every route but ``GET /files/{token}`` (signed URL) needs a verified caller and ``media.*`` rights on
the organization chain (``ews.security``).
"""

from __future__ import annotations

from typing import Any, Literal

from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException, NotFoundException
from foundation.exceptions.http_exceptions import RequestEntityTooLarge
from foundation.http import BaseController, delete, get, patch, post, put, status
from foundation.http.context import Context

from ews.authz import EwsResources, granted_permissions
from ews.security import authorize, current_scope
from ews.shared import raw_response, read_form

from . import _service as svc
from ._settings import media_settings
from .schemas import (
    MediaAssetOut,
    MediaAssetPage,
    MediaAssetUpdate,
    MediaBulkRequest,
    MediaCountOut,
    MediaDownloadOut,
    MediaFolderCreate,
    MediaFolderOut,
    MediaFolderUpdate,
    MediaResolveOut,
    MediaResolveRequest,
    MediaStorageOut,
    MediaUsageOut,
)

ASSET = EwsResources.MEDIA_ASSET.value
FOLDER = EwsResources.MEDIA_FOLDER.value


async def _upload_file(ctx: Context) -> tuple[bytes, str | None, Any]:
    settings = media_settings()
    length = ctx.req.headers.get('content-length')
    if length and length.isdigit() and int(length) > settings.max_upload_bytes + 64 * 1024:
        raise RequestEntityTooLarge(detail='file too large')
    form = await read_form(ctx.req)
    upload = form.get('file')
    if upload is None or not hasattr(upload, 'read'):
        raise ClientException(detail='multipart field "file" is required')
    data = await upload.read()
    if not data:
        raise ClientException(detail='file is empty')
    return data, getattr(upload, 'filename', None), form


def _field(form: Any, name: str) -> str | None:
    value = form.get(name)
    return value if isinstance(value, str) and value.strip() else None


class MediaAssetController(BaseController):
    api_prefix = '/api/v1/media'
    tags = ('Media Library',)

    @get('/assets', summary='List media files (quick tabs, folder, search, sort, paging)')
    @db_context_session
    async def list_assets(
        self,
        session: DBAsyncScopedSession,
        tab: Literal['all', 'recent', 'favorites', 'images', 'videos', 'audio', 'trash'] = 'all',
        folder_id: str | None = None,
        kind: str | None = None,
        q: str | None = None,
        sort: Literal['name', 'size', 'created', 'updated'] | None = None,
        order: Literal['asc', 'desc'] | None = None,
        limit: int = 60,
        offset: int = 0,
    ) -> MediaAssetPage:
        scope = await current_scope()
        await authorize(scope, ASSET, 'read')
        rows, total = await svc.list_assets(
            session, scope, tab=tab, folder_id=folder_id, kind=kind, q=q, sort=sort, order=order, limit=limit, offset=offset
        )
        return MediaAssetPage(items=await svc.outputs(session, scope, rows), total=total, limit=limit, offset=offset)

    @post('/assets', status_code=status.HTTP_201_CREATED, summary='Upload a media file (multipart "file")')
    @db_context_session(auto_commit=True)
    async def upload(self, ctx: Context, session: DBAsyncScopedSession) -> MediaAssetOut:
        scope = await current_scope()
        await authorize(scope, ASSET, 'create')
        data, filename, form = await _upload_file(ctx)
        asset = await svc.upload(
            session,
            scope,
            data,
            filename,
            folder_id=_field(form, 'folder_id'),
            title=_field(form, 'title'),
            alt=_field(form, 'alt'),
        )
        return (await svc.outputs(session, scope, [asset]))[0]

    @get('/assets/{asset_id}')
    @db_context_session
    async def get_asset(self, asset_id: str, session: DBAsyncScopedSession) -> MediaAssetOut:
        scope = await current_scope()
        await authorize(scope, ASSET, 'read')
        asset = await svc.get_asset(session, scope, asset_id, deleted=None)
        return (await svc.outputs(session, scope, [asset]))[0]

    @patch('/assets/{asset_id}', summary='Edit title, alt text, caption, focal point or folder')
    @db_context_session(auto_commit=True)
    async def update_asset(self, asset_id: str, data: MediaAssetUpdate, session: DBAsyncScopedSession) -> MediaAssetOut:
        scope = await current_scope()
        await authorize(scope, ASSET, 'update')
        asset = await svc.update_asset(session, scope, await svc.get_asset(session, scope, asset_id), data)
        return (await svc.outputs(session, scope, [asset]))[0]

    @put('/assets/{asset_id}/file', summary='Replace the file (same id: every use shows the new file)')
    @db_context_session(auto_commit=True)
    async def replace_file(self, asset_id: str, ctx: Context, session: DBAsyncScopedSession) -> MediaAssetOut:
        scope = await current_scope()
        await authorize(scope, ASSET, 'update')
        asset = await svc.get_asset(session, scope, asset_id)
        data, filename, _ = await _upload_file(ctx)
        await svc.replace_file(session, scope, asset, data, filename)
        return (await svc.outputs(session, scope, [asset]))[0]

    @delete('/assets/{asset_id}', status_code=status.HTTP_204_NO_CONTENT, summary='Move to the trash (or delete for good)')
    @db_context_session(auto_commit=True)
    async def delete_asset(
        self, asset_id: str, session: DBAsyncScopedSession, permanent: bool = False, force: bool = False
    ) -> None:
        scope = await current_scope()
        await authorize(scope, ASSET, 'delete')
        if permanent:
            await svc.purge(session, scope, [await svc.get_asset(session, scope, asset_id, deleted=True)])
        else:
            await svc.trash(session, scope, [await svc.get_asset(session, scope, asset_id)], force=force)

    @post('/assets/{asset_id}/restore')
    @db_context_session(auto_commit=True)
    async def restore_asset(self, asset_id: str, session: DBAsyncScopedSession) -> MediaAssetOut:
        scope = await current_scope()
        await authorize(scope, ASSET, 'delete')
        asset = await svc.get_asset(session, scope, asset_id, deleted=True)
        await svc.restore(session, [asset])
        return (await svc.outputs(session, scope, [asset]))[0]

    @put('/assets/{asset_id}/favorite', status_code=status.HTTP_204_NO_CONTENT)
    @db_context_session(auto_commit=True)
    async def add_favorite(self, asset_id: str, session: DBAsyncScopedSession) -> None:
        scope = await current_scope()
        await authorize(scope, ASSET, 'read')
        await svc.set_favorite(session, scope, await svc.get_asset(session, scope, asset_id), True)

    @delete('/assets/{asset_id}/favorite', status_code=status.HTTP_204_NO_CONTENT)
    @db_context_session(auto_commit=True)
    async def remove_favorite(self, asset_id: str, session: DBAsyncScopedSession) -> None:
        scope = await current_scope()
        await authorize(scope, ASSET, 'read')
        await svc.set_favorite(session, scope, await svc.get_asset(session, scope, asset_id, deleted=None), False)

    @get('/assets/{asset_id}/usages', summary='Where the file is used (pages, …)')
    @db_context_session
    async def usages(self, asset_id: str, session: DBAsyncScopedSession) -> list[MediaUsageOut]:
        scope = await current_scope()
        await authorize(scope, ASSET, 'read')
        return await svc.usages_of(session, await svc.get_asset(session, scope, asset_id, deleted=None))

    @get('/assets/{asset_id}/download', summary='Signed download URL of the original')
    @db_context_session
    async def download(self, asset_id: str, session: DBAsyncScopedSession) -> MediaDownloadOut:
        scope = await current_scope()
        await authorize(scope, ASSET, 'read')
        asset = await svc.get_asset(session, scope, asset_id, deleted=None)
        url = await svc.file_url(asset.tenant_id, asset.key, asset.mime, download=asset.filename)
        return MediaDownloadOut(url=url, filename=asset.filename)

    @post('/assets/resolve', summary='Delivery URLs (with responsive variants) of assets by id')
    @db_context_session
    async def resolve(self, data: MediaResolveRequest, session: DBAsyncScopedSession) -> MediaResolveOut:
        scope = await current_scope()
        await authorize(scope, ASSET, 'read')
        assets = await svc.assets_by_ids(session, scope, data.ids, deleted=False)
        return MediaResolveOut(items=[await svc.resolve(a) for a in assets])

    @post('/assets/bulk', summary='Move, trash, restore or delete several files')
    @db_context_session(auto_commit=True)
    async def bulk(self, data: MediaBulkRequest, session: DBAsyncScopedSession) -> MediaCountOut:
        scope = await current_scope()
        if data.action == 'move':
            await authorize(scope, ASSET, 'update')
            assets = await svc.assets_by_ids(session, scope, data.ids, deleted=False)
            for asset in assets:
                await svc.update_asset(session, scope, asset, MediaAssetUpdate(folder_id=data.folder_id))
            return MediaCountOut(count=len(assets))
        await authorize(scope, ASSET, 'delete')
        if data.action == 'trash':
            return MediaCountOut(count=await svc.trash(session, scope, await svc.assets_by_ids(session, scope, data.ids, deleted=False), force=True))
        if data.action == 'restore':
            return MediaCountOut(count=await svc.restore(session, await svc.assets_by_ids(session, scope, data.ids, deleted=True)))
        return MediaCountOut(count=await svc.purge(session, scope, await svc.assets_by_ids(session, scope, data.ids, deleted=True)))

    @delete('/trash', summary='Empty the trash')
    @db_context_session(auto_commit=True)
    async def empty_trash(self, session: DBAsyncScopedSession) -> MediaCountOut:
        scope = await current_scope()
        await authorize(scope, ASSET, 'delete')
        rows, _ = await svc.list_assets(session, scope, tab='trash', limit=200)
        count = 0
        while rows:
            count += await svc.purge(session, scope, rows)
            rows, _ = await svc.list_assets(session, scope, tab='trash', limit=200)
        return MediaCountOut(count=count)

    @get('/storage', summary='Storage used by kind, quota and upload limits')
    @db_context_session
    async def storage(self, session: DBAsyncScopedSession) -> MediaStorageOut:
        scope = await current_scope()
        await authorize(scope, ASSET, 'read')
        out = await svc.storage(session, scope)
        if scope.is_dev:
            out.permissions = [f'{r}:{a}' for r in (ASSET, FOLDER) for a in ('create', 'read', 'update', 'delete')]
        else:
            out.permissions = sorted(await granted_permissions(scope.user_id, scope.org_domains(), 'media'))
        return out

    @get('/files/{token}', summary='File bytes behind a signed URL (no session needed)')
    async def file(self, token: str, ctx: Context) -> Any:
        claims = svc.read_file_token(token)
        if claims is None:
            raise NotFoundException(detail='link expired or invalid')
        store = await svc.tenant_store(claims['t'])
        blob = await store.get(claims['k'])
        if blob is None:
            raise NotFoundException(detail='file not found')
        mime = claims.get('m') or blob.info.content_type or 'application/octet-stream'
        headers = {
            'cache-control': 'private, max-age=3600',
            'x-content-type-options': 'nosniff',
            'cross-origin-resource-policy': 'cross-origin',
        }
        if mime == 'image/svg+xml':
            headers['content-security-policy'] = "default-src 'none'; style-src 'unsafe-inline'; img-src data:"
        if claims.get('d'):
            safe = ''.join(c for c in str(claims['d']) if c.isprintable() and c not in '"\\')
            headers['content-disposition'] = f'attachment; filename="{safe}"'
        if blob.info.etag:
            headers['etag'] = f'"{blob.info.etag}"'
        return raw_response(blob.body, media_type=mime, headers=headers, request=ctx.req)


class MediaFolderController(BaseController):
    api_prefix = '/api/v1/media/folders'
    tags = ('Media Library',)

    @get('/')
    @db_context_session
    async def list_folders(self, session: DBAsyncScopedSession) -> list[MediaFolderOut]:
        scope = await current_scope()
        await authorize(scope, FOLDER, 'read')
        return await svc.list_folders(session, scope)

    @post('/', status_code=status.HTTP_201_CREATED)
    @db_context_session(auto_commit=True)
    async def create_folder(self, data: MediaFolderCreate, session: DBAsyncScopedSession) -> MediaFolderOut:
        scope = await current_scope()
        await authorize(scope, FOLDER, 'create')
        folder = await svc.create_folder(session, scope, data.name, data.parent_id, data.color)
        return next(f for f in await svc.list_folders(session, scope) if f.id == str(folder.id))

    @patch('/{folder_id}')
    @db_context_session(auto_commit=True)
    async def update_folder(self, folder_id: str, data: MediaFolderUpdate, session: DBAsyncScopedSession) -> MediaFolderOut:
        scope = await current_scope()
        await authorize(scope, FOLDER, 'update')
        folder = await svc.update_folder(session, scope, folder_id, data.name, data.color, data.parent_id)
        return next(f for f in await svc.list_folders(session, scope) if f.id == str(folder.id))

    @delete('/{folder_id}', status_code=status.HTTP_204_NO_CONTENT, summary='Delete a folder (its content moves up)')
    @db_context_session(auto_commit=True)
    async def delete_folder(self, folder_id: str, session: DBAsyncScopedSession) -> None:
        scope = await current_scope()
        await authorize(scope, FOLDER, 'delete')
        await svc.delete_folder(session, scope, folder_id)
