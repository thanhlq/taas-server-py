"""Media library use cases (``session`` = the request's DB session; ``scope`` = verified caller).

Storage (taas-specs/platform/storage): the tenant's private storage through ``StorageResolverT.root`` — originals in the
``upload`` kind ``uploads/media/<organization_id>/<asset_id>/<version>/original.<ext>``, variants in the ``derived``
kind ``derived/media/<asset_id>/<version>/w640.webp`` … (keys stored relative to the tenant root). A new version on
"replace file" keeps old URLs from serving stale caches; the previous version is deleted after the switch.
Publishing copies files to the public CDN bucket (``ews.sites._cdn``), never from here.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import time
import uuid
from collections.abc import Iterable, Sequence
from datetime import timedelta
from typing import Any
from uuid import UUID

import msgspec
from db.models.media import MediaAsset, MediaFavorite, MediaFolder, MediaUsage
from foundation.blob import BlobPresignOptions, BlobPutOptions, StorageResolverT, TenantBlobStoreT, kind_key
from foundation.exceptions import ClientException, NotFoundException
from foundation.exceptions.http_exceptions import RequestEntityTooLarge
from foundation.db.types import DBAsyncScopedSession
from foundation.state import get_service
from sqlalchemy import Select, and_, delete, func, or_, select

from ews.security import RequestScope
from ews.shared import parse_uuid, sign_token, utcnow, verify_token

from ._processing import MediaRejected, ProcessedMedia, process_media
from ._settings import MediaSettings, media_settings
from .schemas import (
    MediaAssetOut,
    MediaAssetUpdate,
    MediaFolderOut,
    MediaKindUsage,
    MediaResolved,
    MediaSource,
    MediaStorageOut,
    MediaTab,
    MediaUsageOut,
)

FILE_TOKEN_PURPOSE = 'media.file'
MAX_FOLDER_DEPTH = 5
RECENT_DAYS = 30
_KIND_OF_TAB = {'images': 'image', 'videos': 'video', 'audio': 'audio'}


class ConflictException(ClientException):
    status_code = 409


class UnsupportedMediaException(ClientException):
    status_code = 415


_storage_override: list[StorageResolverT | None] = [None]


def use_storage(resolver: StorageResolverT | None) -> None:
    """Tests: replace the registered storage resolver (``None`` restores ``foundation.state``)."""
    _storage_override[0] = resolver


def storage_resolver() -> StorageResolverT:
    return _storage_override[0] or get_service(StorageResolverT)


async def tenant_store(tenant_id: UUID | str) -> TenantBlobStoreT:
    """The tenant root of the private storage (keys start with ``uploads/`` / ``derived/``)."""
    return await storage_resolver().root(tenant_id)


# --- keys & URLs ----------------------------------------------------------------------------------


def _version_prefixes(organization_id: UUID, asset_id: UUID) -> tuple[str, str]:
    """``(original prefix, variants prefix)`` of a new version, relative to the tenant root."""
    version = uuid.uuid4().hex[:8]
    return (
        kind_key('upload', f'media/{organization_id}/{asset_id}/{version}/'),
        kind_key('derived', f'media/{asset_id}/{version}/'),
    )


def _all_keys(asset: MediaAsset) -> list[str]:
    return [asset.key, *(v['key'] for v in (asset.variants or {}).values() if isinstance(v, dict) and v.get('key'))]


def _exp(now: float | None = None) -> int:
    """Expiry rounded to the hour (1–2 h ahead) so URLs stay stable and cacheable within an hour."""
    hour = 3600
    return (math.floor((now or time.time()) / hour) + 2) * hour


def file_token(tenant_id: UUID, key: str, mime: str, *, download: str | None = None, exp: int | None = None) -> str:
    payload: dict[str, Any] = {'t': str(tenant_id), 'k': key, 'm': mime, 'exp': exp or _exp()}
    if download:
        payload['d'] = download
    return sign_token(payload, purpose=FILE_TOKEN_PURPOSE)


def read_file_token(token: str) -> dict[str, Any] | None:
    return verify_token(token, purpose=FILE_TOKEN_PURPOSE)


async def file_url(
    tenant_id: UUID, key: str, mime: str, *, download: str | None = None, settings: MediaSettings | None = None
) -> str:
    settings = settings or media_settings()
    if settings.delivery == 'presigned':
        store = await tenant_store(tenant_id)
        return await store.presign(
            key, BlobPresignOptions(method='GET', expires_in=2 * 3600, download_name=download)
        )
    return f'{settings.public_base_url}/api/v1/media/files/{file_token(tenant_id, key, mime, download=download)}'


def _variant(asset: MediaAsset, name: str) -> dict[str, Any] | None:
    v = (asset.variants or {}).get(name)
    return v if isinstance(v, dict) else None


def _best_variant(asset: MediaAsset, min_width: int) -> dict[str, Any] | None:
    webps = sorted(
        (v for v in (asset.variants or {}).values() if isinstance(v, dict) and v.get('format') == 'webp'),
        key=lambda v: v.get('width') or 0,
    )
    return next((v for v in webps if (v.get('width') or 0) >= min_width), webps[-1] if webps else None)


async def to_out(asset: MediaAsset, *, favorite: bool = False, usage_count: int = 0) -> MediaAssetOut:
    url = await file_url(asset.tenant_id, asset.key, asset.mime)
    thumb = preview = None
    if asset.kind == 'image':
        small, large = _best_variant(asset, 320), _best_variant(asset, 1280)
        thumb = await file_url(asset.tenant_id, small['key'], 'image/webp') if small else url
        preview = await file_url(asset.tenant_id, large['key'], 'image/webp') if large else url
    return MediaAssetOut(
        id=str(asset.id),
        kind=asset.kind,
        title=asset.title,
        filename=asset.filename,
        ext=asset.ext,
        mime=asset.mime,
        size=asset.size,
        width=asset.width,
        height=asset.height,
        alt=asset.alt,
        caption=asset.caption,
        focal_x=asset.focal_x,
        focal_y=asset.focal_y,
        folder_id=str(asset.folder_id) if asset.folder_id else None,
        favorite=favorite,
        url=url,
        thumb_url=thumb,
        preview_url=preview,
        variants=sorted((asset.variants or {}).keys()),
        usage_count=usage_count,
        created_by=str(asset.created_by) if asset.created_by else None,
        created_at=asset.created_at,
        updated_at=asset.updated_at,
        deleted_at=asset.deleted_at,
    )


# --- queries --------------------------------------------------------------------------------------


def _scoped(scope: RequestScope) -> Any:
    return and_(MediaAsset.tenant_id == scope.tenant_id, MediaAsset.organization_id == scope.organization_id)


async def get_asset(session: DBAsyncScopedSession, scope: RequestScope, asset_id: object, *, deleted: bool | None = False) -> MediaAsset:
    """An asset of the scope's organization (``deleted``: ``False`` live only, ``True`` trash only, ``None`` both)."""
    aid = parse_uuid(asset_id, 'asset')
    stmt = select(MediaAsset).where(_scoped(scope), MediaAsset.id == aid)
    if deleted is False:
        stmt = stmt.where(MediaAsset.deleted_at.is_(None))
    elif deleted is True:
        stmt = stmt.where(MediaAsset.deleted_at.is_not(None))
    asset = await session.scalar(stmt)
    if asset is None:
        raise NotFoundException(detail='asset not found')
    return asset


async def _favorites(session: DBAsyncScopedSession, user_id: UUID, ids: Sequence[UUID]) -> set[UUID]:
    if not ids:
        return set()
    rows = await session.scalars(
        select(MediaFavorite.asset_id).where(MediaFavorite.user_id == user_id, MediaFavorite.asset_id.in_(ids))
    )
    return set(rows)


async def _usage_counts(session: DBAsyncScopedSession, ids: Sequence[UUID]) -> dict[UUID, int]:
    if not ids:
        return {}
    rows = await session.execute(
        select(MediaUsage.asset_id, func.count()).where(MediaUsage.asset_id.in_(ids)).group_by(MediaUsage.asset_id)
    )
    return dict(rows.tuples().all())


async def outputs(session: DBAsyncScopedSession, scope: RequestScope, assets: Sequence[MediaAsset]) -> list[MediaAssetOut]:
    ids = [a.id for a in assets]
    favs = await _favorites(session, scope.user_id, ids)
    usages = await _usage_counts(session, ids)
    return list(
        await asyncio.gather(*(to_out(a, favorite=a.id in favs, usage_count=usages.get(a.id, 0)) for a in assets))
    )


def _sorted(stmt: Select[Any], sort: str | None, order: str | None, tab: str) -> Select[Any]:
    column = {
        'name': func.lower(MediaAsset.title),
        'size': MediaAsset.size,
        'created': MediaAsset.created_at,
        'updated': MediaAsset.updated_at,
    }.get(sort or '', MediaAsset.deleted_at if tab == 'trash' else MediaAsset.updated_at if tab == 'recent' else MediaAsset.created_at)
    descending = (order or ('asc' if sort == 'name' else 'desc')) == 'desc'
    return stmt.order_by(column.desc() if descending else column.asc(), MediaAsset.id.desc())


async def list_assets(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    *,
    tab: MediaTab = 'all',
    folder_id: str | None = None,
    kind: str | None = None,
    q: str | None = None,
    sort: str | None = None,
    order: str | None = None,
    limit: int = 60,
    offset: int = 0,
) -> tuple[list[MediaAsset], int]:
    stmt = select(MediaAsset).where(_scoped(scope))
    stmt = stmt.where(MediaAsset.deleted_at.is_not(None) if tab == 'trash' else MediaAsset.deleted_at.is_(None))
    if tab == 'recent':
        stmt = stmt.where(MediaAsset.updated_at >= utcnow() - timedelta(days=RECENT_DAYS))
    elif tab == 'favorites':
        stmt = stmt.join(
            MediaFavorite, and_(MediaFavorite.asset_id == MediaAsset.id, MediaFavorite.user_id == scope.user_id)
        )
    if tab in _KIND_OF_TAB or kind:
        stmt = stmt.where(MediaAsset.kind == (_KIND_OF_TAB.get(tab) or kind))
    if folder_id == 'root':
        stmt = stmt.where(MediaAsset.folder_id.is_(None))
    elif folder_id:
        stmt = stmt.where(MediaAsset.folder_id == parse_uuid(folder_id, 'folder', not_found=False))
    if q and q.strip():
        like = f'%{q.strip().lower()}%'
        stmt = stmt.where(
            or_(
                func.lower(MediaAsset.title).like(like),
                func.lower(MediaAsset.filename).like(like),
                func.lower(func.coalesce(MediaAsset.alt, '')).like(like),
            )
        )
    total = await session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    limit = max(1, min(limit, 200))
    rows = await session.scalars(_sorted(stmt, sort, order, tab).limit(limit).offset(max(0, offset)))
    return list(rows), total


# --- upload / replace -----------------------------------------------------------------------------


async def _used_bytes(session: DBAsyncScopedSession, tenant_id: UUID) -> int:
    used = await session.scalar(
        select(func.coalesce(func.sum(MediaAsset.size + MediaAsset.variants_size), 0)).where(
            MediaAsset.tenant_id == tenant_id
        )
    )
    return int(used or 0)


def _process(data: bytes, filename: str, settings: MediaSettings) -> ProcessedMedia:
    try:
        processed = process_media(data, settings.variant_widths, settings.avif)
    except MediaRejected as error:
        raise UnsupportedMediaException(detail=str(error), extra={'code': error.code}) from error
    if len(data) > settings.max_bytes(processed.kind):
        raise RequestEntityTooLarge(
            detail=f'{processed.kind} files are limited to {settings.max_bytes(processed.kind) // (1024 * 1024)} MB'
        )
    return processed


async def _store(
    store: TenantBlobStoreT, prefixes: tuple[str, str], processed: ProcessedMedia, filename: str
) -> tuple[str, dict[str, Any], int]:
    original_prefix, variants_prefix = prefixes
    key = f'{original_prefix}original.{processed.ext}'
    cache = 'private, max-age=31536000, immutable'
    await store.put(key, processed.body, BlobPutOptions(content_type=processed.mime, cache_control=cache))
    variants: dict[str, Any] = {}
    total = 0
    for v in processed.variants:
        vkey = f'{variants_prefix}{v.name}'
        await store.put(vkey, v.body, BlobPutOptions(content_type=v.mime, cache_control=cache))
        variants[v.name] = {
            'key': vkey, 'width': v.width, 'height': v.height, 'format': v.format, 'size': len(v.body),
            'sha256': hashlib.sha256(v.body).hexdigest(),
        }
        total += len(v.body)
    return key, variants, total


def _title(filename: str) -> str:
    stem = filename.rsplit('/', 1)[-1].rsplit('\\', 1)[-1]
    stem = stem.rsplit('.', 1)[0] if '.' in stem else stem
    return (stem.replace('_', ' ').replace('-', ' ').strip() or 'Untitled')[:255]


def _safe_filename(filename: str | None, ext: str) -> str:
    name = (filename or '').rsplit('/', 1)[-1].rsplit('\\', 1)[-1].strip() or f'file.{ext}'
    return ''.join(c for c in name if c.isprintable())[:255]


async def _check_quota(session: DBAsyncScopedSession, scope: RequestScope, incoming: int, settings: MediaSettings) -> None:
    if settings.quota_bytes and await _used_bytes(session, scope.tenant_id) + incoming > settings.quota_bytes:
        raise ConflictException(detail='storage quota reached: empty the trash or delete unused files', extra={'code': 'quota_exceeded'})


async def _folder(session: DBAsyncScopedSession, scope: RequestScope, folder_id: str | None) -> MediaFolder | None:
    if not folder_id:
        return None
    fid = parse_uuid(folder_id, 'folder', not_found=False)
    folder = await session.scalar(
        select(MediaFolder).where(
            MediaFolder.id == fid,
            MediaFolder.tenant_id == scope.tenant_id,
            MediaFolder.organization_id == scope.organization_id,
        )
    )
    if folder is None:
        raise ClientException(detail='folder not found')
    return folder


async def upload(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    data: bytes,
    filename: str | None,
    *,
    folder_id: str | None = None,
    title: str | None = None,
    alt: str | None = None,
    settings: MediaSettings | None = None,
) -> MediaAsset:
    settings = settings or media_settings()
    if len(data) > settings.max_upload_bytes:
        raise RequestEntityTooLarge(detail='file too large')
    folder = await _folder(session, scope, folder_id)
    processed = await asyncio.to_thread(_process, data, filename or '', settings)
    await _check_quota(session, scope, len(processed.body) + sum(len(v.body) for v in processed.variants), settings)
    asset_id = uuid.uuid7()
    store = await tenant_store(scope.tenant_id)
    key, variants, variants_size = await _store(store, _version_prefixes(scope.organization_id, asset_id), processed, filename or '')
    name = _safe_filename(filename, processed.ext)
    asset = MediaAsset(
        id=asset_id,
        tenant_id=scope.tenant_id,
        organization_id=scope.organization_id,
        folder_id=folder.id if folder else None,
        kind=processed.kind,
        filename=name,
        title=(title or '').strip()[:255] or _title(name),
        ext=processed.ext,
        mime=processed.mime,
        size=len(processed.body),
        width=processed.width,
        height=processed.height,
        alt=(alt or '').strip()[:500] or None,
        key=key,
        variants=variants,
        variants_size=variants_size,
        checksum=hashlib.sha256(processed.body).hexdigest(),
        created_by=scope.user_id,
        updated_by=scope.user_id,
    )
    session.add(asset)
    await session.flush()
    return asset


async def replace_file(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    asset: MediaAsset,
    data: bytes,
    filename: str | None,
    settings: MediaSettings | None = None,
) -> MediaAsset:
    """Replace the file of an asset everywhere it is used (same id; Site-0402 "replace everywhere")."""
    settings = settings or media_settings()
    processed = await asyncio.to_thread(_process, data, filename or '', settings)
    if processed.kind != asset.kind:
        raise ClientException(detail=f'replace a {asset.kind} with a {asset.kind}')
    await _check_quota(session, scope, len(processed.body), settings)
    store = await tenant_store(scope.tenant_id)
    old_keys = _all_keys(asset)
    key, variants, variants_size = await _store(store, _version_prefixes(asset.organization_id, asset.id), processed, filename or '')
    asset.key, asset.variants, asset.variants_size = key, variants, variants_size
    asset.size, asset.width, asset.height = len(processed.body), processed.width, processed.height
    asset.mime, asset.ext = processed.mime, processed.ext
    asset.filename = _safe_filename(filename, processed.ext)
    asset.checksum = hashlib.sha256(processed.body).hexdigest()
    asset.updated_by = scope.user_id
    asset.updated_at = utcnow()
    await session.flush()
    await store.delete_many(old_keys)
    return asset


# --- edit / trash ---------------------------------------------------------------------------------


async def update_asset(session: DBAsyncScopedSession, scope: RequestScope, asset: MediaAsset, data: MediaAssetUpdate) -> MediaAsset:
    if data.title is not None:
        if not data.title.strip():
            raise ClientException(detail='title is required')
        asset.title = data.title.strip()[:255]
    if data.alt is not None:
        asset.alt = data.alt.strip()[:500] or None
    if data.caption is not None:
        asset.caption = data.caption.strip()[:2000] or None
    for name in ('focal_x', 'focal_y'):
        value = getattr(data, name)
        if value is not None:
            if not 0 <= value <= 1:
                raise ClientException(detail=f'{name} must be between 0 and 1')
            setattr(asset, name, float(value))
    if data.folder_id is not msgspec.UNSET:
        folder = await _folder(session, scope, data.folder_id)
        asset.folder_id = folder.id if folder else None
    asset.updated_by = scope.user_id
    asset.updated_at = utcnow()
    await session.flush()
    return asset


async def trash(session: DBAsyncScopedSession, scope: RequestScope, assets: Iterable[MediaAsset], *, force: bool = False) -> int:
    assets = list(assets)
    if not force:
        used = await _usage_counts(session, [a.id for a in assets])
        if used:
            raise ConflictException(
                detail='file is used by published content; confirm to move it to the trash anyway',
                extra={'code': 'asset_in_use', 'usages': sum(used.values())},
            )
    now = utcnow()
    for a in assets:
        a.deleted_at, a.deleted_by = now, scope.user_id
    await session.flush()
    return len(assets)


async def restore(session: DBAsyncScopedSession, assets: Iterable[MediaAsset]) -> int:
    count = 0
    for a in assets:
        a.deleted_at, a.deleted_by = None, None
        count += 1
    await session.flush()
    return count


async def purge(session: DBAsyncScopedSession, scope: RequestScope, assets: Iterable[MediaAsset]) -> int:
    """Delete files and rows for good (from the trash)."""
    assets = list(assets)
    if not assets:
        return 0
    store = await tenant_store(scope.tenant_id)
    keys = [k for a in assets for k in _all_keys(a)]
    for a in assets:
        await session.delete(a)
    await session.flush()
    await store.delete_many(keys)
    return len(assets)


async def assets_by_ids(session: DBAsyncScopedSession, scope: RequestScope, ids: Sequence[str], *, deleted: bool | None) -> list[MediaAsset]:
    uuids = [parse_uuid(i, 'asset', not_found=False) for i in ids[:500]]
    stmt = select(MediaAsset).where(_scoped(scope), MediaAsset.id.in_(uuids))
    if deleted is False:
        stmt = stmt.where(MediaAsset.deleted_at.is_(None))
    elif deleted is True:
        stmt = stmt.where(MediaAsset.deleted_at.is_not(None))
    return list(await session.scalars(stmt))


async def set_favorite(session: DBAsyncScopedSession, scope: RequestScope, asset: MediaAsset, on: bool) -> None:
    existing = await session.scalar(
        select(MediaFavorite).where(MediaFavorite.user_id == scope.user_id, MediaFavorite.asset_id == asset.id)
    )
    if on and existing is None:
        session.add(MediaFavorite(tenant_id=scope.tenant_id, user_id=scope.user_id, asset_id=asset.id))
    elif not on and existing is not None:
        await session.delete(existing)
    await session.flush()


# --- folders --------------------------------------------------------------------------------------


async def list_folders(session: DBAsyncScopedSession, scope: RequestScope) -> list[MediaFolderOut]:
    folders = list(
        await session.scalars(
            select(MediaFolder)
            .where(MediaFolder.tenant_id == scope.tenant_id, MediaFolder.organization_id == scope.organization_id)
            .order_by(func.lower(MediaFolder.name))
        )
    )
    counts = dict(
        (
            await session.execute(
                select(MediaAsset.folder_id, func.count())
                .where(_scoped(scope), MediaAsset.deleted_at.is_(None), MediaAsset.folder_id.is_not(None))
                .group_by(MediaAsset.folder_id)
            )
        ).all()
    )
    return [
        MediaFolderOut(
            id=str(f.id),
            name=f.name,
            parent_id=str(f.parent_id) if f.parent_id else None,
            color=f.color,
            asset_count=counts.get(f.id, 0),
            created_at=f.created_at,
        )
        for f in folders
    ]


async def _depth(session: DBAsyncScopedSession, folder: MediaFolder | None) -> int:
    depth = 0
    while folder is not None:
        depth += 1
        folder = await session.get(MediaFolder, folder.parent_id) if folder.parent_id else None
    return depth


def _folder_name(name: str | None) -> str:
    clean = (name or '').strip()
    if not clean or len(clean) > 120 or any(c in clean for c in '/\\'):
        raise ClientException(detail='folder name must be 1 to 120 characters without / or \\')
    return clean


async def _name_taken(session: DBAsyncScopedSession, scope: RequestScope, parent_id: UUID | None, name: str, exclude: UUID | None = None) -> bool:
    stmt = select(MediaFolder.id).where(
        MediaFolder.organization_id == scope.organization_id,
        MediaFolder.parent_id.is_(None) if parent_id is None else MediaFolder.parent_id == parent_id,
        func.lower(MediaFolder.name) == name.lower(),
    )
    if exclude:
        stmt = stmt.where(MediaFolder.id != exclude)
    return (await session.scalar(stmt)) is not None


async def create_folder(session: DBAsyncScopedSession, scope: RequestScope, name: str, parent_id: str | None, color: str | None) -> MediaFolder:
    clean = _folder_name(name)
    parent = await _folder(session, scope, parent_id)
    if await _depth(session, parent) >= MAX_FOLDER_DEPTH:
        raise ClientException(detail=f'folders nest at most {MAX_FOLDER_DEPTH} levels')
    if await _name_taken(session, scope, parent.id if parent else None, clean):
        raise ConflictException(detail='a folder with this name already exists here')
    folder = MediaFolder(
        tenant_id=scope.tenant_id,
        organization_id=scope.organization_id,
        parent_id=parent.id if parent else None,
        name=clean,
        color=(color or None),
        created_by=scope.user_id,
    )
    session.add(folder)
    await session.flush()
    return folder


async def update_folder(session: DBAsyncScopedSession, scope: RequestScope, folder_id: str, name: str | None, color: str | None, parent_id: object) -> MediaFolder:
    folder = await _folder(session, scope, folder_id)
    assert folder is not None
    target_parent = folder.parent_id
    if parent_id is not msgspec.UNSET:
        parent = await _folder(session, scope, parent_id)  # type: ignore[arg-type]
        cursor = parent
        while cursor is not None:  # no cycles
            if cursor.id == folder.id:
                raise ClientException(detail='a folder cannot move into itself')
            cursor = await session.get(MediaFolder, cursor.parent_id) if cursor.parent_id else None
        if await _depth(session, parent) >= MAX_FOLDER_DEPTH:
            raise ClientException(detail=f'folders nest at most {MAX_FOLDER_DEPTH} levels')
        target_parent = parent.id if parent else None
    new_name = _folder_name(name) if name is not None else folder.name
    if (new_name.lower() != folder.name.lower() or target_parent != folder.parent_id) and await _name_taken(
        session, scope, target_parent, new_name, exclude=folder.id
    ):
        raise ConflictException(detail='a folder with this name already exists here')
    folder.name, folder.parent_id = new_name, target_parent
    if color is not None:
        folder.color = color or None
    await session.flush()
    return folder


async def delete_folder(session: DBAsyncScopedSession, scope: RequestScope, folder_id: str) -> None:
    """Delete a folder: its files and sub-folders move to its parent."""
    folder = await _folder(session, scope, folder_id)
    assert folder is not None
    children = list(await session.scalars(select(MediaFolder).where(MediaFolder.parent_id == folder.id)))
    for child in children:
        if await _name_taken(session, scope, folder.parent_id, child.name, exclude=child.id):
            child.name = f'{child.name} ({folder.name})'[:120]
        child.parent_id = folder.parent_id
    assets = await session.scalars(select(MediaAsset).where(MediaAsset.folder_id == folder.id))
    for a in assets:
        a.folder_id = folder.parent_id
    await session.flush()
    await session.delete(folder)
    await session.flush()


# --- usages (called in-process by consumer apps, e.g. sites) ---------------------------------------


async def record_usages(
    session: DBAsyncScopedSession,
    tenant_id: UUID,
    *,
    app: str,
    ref_type: str,
    ref_id: UUID,
    label: str | None,
    asset_ids: Iterable[UUID],
) -> None:
    """Make the usages of one referrer (e.g. a page) exactly ``asset_ids`` (assets of the tenant)."""
    wanted = set(asset_ids)
    if wanted:
        wanted = set(
            await session.scalars(select(MediaAsset.id).where(MediaAsset.tenant_id == tenant_id, MediaAsset.id.in_(wanted)))
        )
    current = {
        u.asset_id: u
        for u in await session.scalars(
            select(MediaUsage).where(
                MediaUsage.tenant_id == tenant_id,
                MediaUsage.app == app,
                MediaUsage.ref_type == ref_type,
                MediaUsage.ref_id == ref_id,
            )
        )
    }
    stale = [aid for aid in current if aid not in wanted]
    if stale:
        await session.execute(
            delete(MediaUsage).where(
                MediaUsage.app == app,
                MediaUsage.ref_type == ref_type,
                MediaUsage.ref_id == ref_id,
                MediaUsage.asset_id.in_(stale),
            )
        )
    now = utcnow()
    for aid in wanted:
        usage = current.get(aid)
        if usage is None:
            session.add(
                MediaUsage(tenant_id=tenant_id, asset_id=aid, app=app, ref_type=ref_type, ref_id=ref_id, label=label, used_at=now)
            )
        else:
            usage.label, usage.used_at = label, now
    await session.flush()


async def usages_of(session: DBAsyncScopedSession, asset: MediaAsset) -> list[MediaUsageOut]:
    rows = await session.scalars(select(MediaUsage).where(MediaUsage.asset_id == asset.id).order_by(MediaUsage.used_at.desc()))
    return [
        MediaUsageOut(app=u.app, ref_type=u.ref_type, ref_id=str(u.ref_id), label=u.label, used_at=u.used_at) for u in rows
    ]


# --- storage / resolve ----------------------------------------------------------------------------


async def storage(session: DBAsyncScopedSession, scope: RequestScope, settings: MediaSettings | None = None) -> MediaStorageOut:
    settings = settings or media_settings()
    rows = await session.execute(
        select(MediaAsset.kind, func.count(), func.coalesce(func.sum(MediaAsset.size + MediaAsset.variants_size), 0))
        .where(_scoped(scope), MediaAsset.deleted_at.is_(None))
        .group_by(MediaAsset.kind)
    )
    by_kind = [MediaKindUsage(kind=k, count=c, size=int(s)) for k, c, s in rows.all()]
    trash_count = await session.scalar(
        select(func.count()).where(_scoped(scope), MediaAsset.deleted_at.is_not(None))
    )
    return MediaStorageOut(
        used=await _used_bytes(session, scope.tenant_id),
        quota=settings.quota_bytes,
        count=sum(k.count for k in by_kind),
        trash_count=int(trash_count or 0),
        by_kind=sorted(by_kind, key=lambda k: k.kind),
        max_upload={'image': settings.max_image_bytes, 'video': settings.max_video_bytes, 'audio': settings.max_audio_bytes},
    )


async def resolve(asset: MediaAsset) -> MediaResolved:
    """Delivery URLs of an asset (original + responsive variants) for pages and the editor canvas."""
    sources = [
        MediaSource(url=await file_url(asset.tenant_id, v['key'], f'image/{v["format"]}'), width=v['width'], format=v['format'])
        for v in sorted(
            (v for v in (asset.variants or {}).values() if isinstance(v, dict)),
            key=lambda v: (v.get('format') != 'avif', v.get('width') or 0),
        )
    ]
    return MediaResolved(
        id=str(asset.id),
        kind=asset.kind,
        mime=asset.mime,
        title=asset.title,
        url=await file_url(asset.tenant_id, asset.key, asset.mime),
        width=asset.width,
        height=asset.height,
        alt=asset.alt,
        focal_x=asset.focal_x,
        focal_y=asset.focal_y,
        sources=sources,
    )
