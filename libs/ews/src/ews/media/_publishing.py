"""Public CDN copies of media library files — shared by every app that publishes (sites, blogs, …).

taas-specs/platform/storage §3 (content ADR C-2): publishing copies every file of the referenced media (original +
variants) from the tenant's private storage to the shared public bucket under ``{tenantId}/{scope}/{sha256}.{ext}``
(``scope`` = ``site/<siteId>``, ``blog/<blogId>`` …) and returns their CDN URLs. Keys are content-hashed: publishing
again copies nothing new. Removing a scope deletes every public copy of that app object. Without a public store
(development, CLI) nothing is copied and URLs stay unset — the renderer then serves ``/_assets``.

- ``asset_map(session, tenant_id, ids)`` — renderer metadata of media (``{id: {kind, mime, …, variants}}``)
- ``publish_assets(session, tenant_id, scope, assets)`` — copies + ``public: {original, variants}`` per asset
- ``remove_public_scope(tenant_id, scope)`` — unpublish / archive / delete (best effort, logged)
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from db.models.media import MediaAsset
from foundation.blob import PublicStoreT
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ServiceUnavailableException
from foundation.state import get_service
from sqlalchemy import select

from ._service import tenant_store

logger = logging.getLogger(__name__)
_CONCURRENCY = 8
_override: list[PublicStoreT | None] = [None]


def use_public_store(store: PublicStoreT | None) -> None:
    """Tests: replace the registered public store (``None`` restores ``foundation.state``)."""
    _override[0] = store


def public_store() -> PublicStoreT | None:
    """The enabled public store, else ``None`` (no CDN configured)."""
    if _override[0] is not None:
        return _override[0]
    try:
        store = get_service(PublicStoreT)
    except Exception:  # not registered (CLI, tests without CDN)
        return None
    return store if store.enabled else None


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f'{parts.scheme}://{parts.netloc}'


async def asset_map(
    session: DBAsyncScopedSession, tenant_id: UUID, ids: Iterable[UUID]
) -> dict[str, Any]:
    """``{asset id: {kind, mime, title, alt, width, height, focal_x, focal_y, version, variants}}`` of the media
    of the tenant (unknown ids are left out) — the ``assets`` of site and blog snapshots."""
    wanted = set(ids)
    if not wanted:
        return {}
    rows = await session.scalars(
        select(MediaAsset).where(
            MediaAsset.tenant_id == tenant_id, MediaAsset.id.in_(wanted)
        )
    )
    return {
        str(a.id): {
            'kind': a.kind,
            'mime': a.mime,
            'title': a.title,
            'alt': a.alt,
            'width': a.width,
            'height': a.height,
            'focal_x': a.focal_x,
            'focal_y': a.focal_y,
            'version': a.key.rsplit('/', 2)[-2] if '/' in a.key else '',
            'variants': {
                name: {
                    'width': v.get('width'),
                    'height': v.get('height'),
                    'format': v.get('format'),
                }
                for name, v in (a.variants or {}).items()
                if isinstance(v, dict)
            },
        }
        for a in rows
    }


async def publish_assets(
    session: DBAsyncScopedSession,
    tenant_id: UUID,
    scope: str,
    assets: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    """Copy the files of ``assets`` (an ``asset_map``) to ``{tenantId}/{scope}/`` on the CDN.

    Returns ``(assets with public: {original, variants} URLs, cdn_origin)``; without a public store or without
    assets: ``(assets unchanged, None)``. 503 when a copy fails (nothing is half-published: the caller's
    transaction is rolled back and the content-hashed copies are reused on the next try).
    """
    store = public_store()
    if store is None or not assets:
        return assets, None
    ids = [UUID(i) for i in assets]
    rows = {
        str(a.id): a
        for a in await session.scalars(
            select(MediaAsset).where(
                MediaAsset.tenant_id == tenant_id, MediaAsset.id.in_(ids)
            )
        )
    }
    private = await tenant_store(tenant_id)
    gate = asyncio.Semaphore(_CONCURRENCY)

    async def copy(key: str, ext: str, content_type: str, sha256: str | None) -> str:
        async def load() -> bytes:
            blob = await private.get(key)
            if blob is None:
                raise FileNotFoundError(key)
            return blob.body

        async with gate:
            return (
                await store.publish(
                    tenant_id,
                    scope,
                    ext=ext,
                    content_type=content_type,
                    load=load,
                    sha256=sha256,
                )
            ).url

    async def one(asset_id: str, asset: MediaAsset) -> tuple[str, dict[str, Any]]:
        original = copy(asset.key, asset.ext, asset.mime, asset.checksum)
        names = [
            n
            for n, v in (asset.variants or {}).items()
            if isinstance(v, dict) and v.get('key')
        ]
        variants = [
            copy(v['key'], v['format'], f'image/{v["format"]}', v.get('sha256'))
            for v in (asset.variants[n] for n in names)
        ]
        urls = await asyncio.gather(original, *variants)
        return asset_id, {
            'original': urls[0],
            'variants': dict(zip(names, urls[1:], strict=True)),
        }

    try:
        results = await asyncio.gather(*(one(i, rows[i]) for i in assets if i in rows))
    except Exception as error:
        logger.exception('CDN copy failed for %s/%s', tenant_id, scope)
        raise ServiceUnavailableException(
            detail='the media could not be copied to the CDN; try again'
        ) from error
    out = dict(assets)
    for asset_id, public in results:
        out[asset_id] = {**out[asset_id], 'public': public}
    return out, _origin(store.base_url)


async def remove_public_scope(tenant_id: UUID, scope: str) -> None:
    """Drop every public copy of ``{tenantId}/{scope}/`` (best effort, logged)."""
    store = public_store()
    if store is None:
        return
    try:
        deleted = await store.delete_scope(tenant_id, scope)
        logger.info('removed %s public objects of %s/%s', deleted, tenant_id, scope)
    except Exception:
        logger.exception(
            'could not remove the public objects of %s/%s', tenant_id, scope
        )
