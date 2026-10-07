"""Public CDN copies of a site's media (taas-specs/storage §3, content ADR C-2).

Publishing a release copies every file of the referenced media (original + variants) from the tenant's private
storage to the shared public bucket under ``{tenantId}/site/{siteId}/{sha256}.{ext}`` and writes the CDN URLs into
the release snapshot (``assets[id].public``, ``cdn_origin``). Unpublish / archive / delete remove the site's prefix;
rollback and restore copy again whatever is missing. Previews never touch the public bucket.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from db.models.media import MediaAsset
from db.models.sites import Site
from foundation.blob import PublicStoreT
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ServiceUnavailableException
from foundation.state import get_service
from sqlalchemy import select

from ews.media._service import tenant_store

logger = logging.getLogger(__name__)
_CONCURRENCY = 8
_override: list[PublicStoreT | None] = [None]


def use_public_store(store: PublicStoreT | None) -> None:
    """Tests: replace the registered public store (``None`` restores ``foundation.state``)."""
    _override[0] = store


def public_store() -> PublicStoreT | None:
    if _override[0] is not None:
        return _override[0]
    try:
        store = get_service(PublicStoreT)
    except Exception:  # not registered (CLI, tests without CDN)
        return None
    return store if store.enabled else None


def site_scope(site_id: UUID | str) -> str:
    return f'site/{site_id}'


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f'{parts.scheme}://{parts.netloc}'


async def publish_snapshot_media(session: DBAsyncScopedSession, site: Site, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Copy the media of ``snapshot`` to the CDN and return it with public URLs (unchanged without a CDN)."""
    store = public_store()
    assets: dict[str, Any] = snapshot.get('assets') or {}
    if store is None or not assets:
        snapshot['cdn_origin'] = _origin(store.base_url) if store and assets else None
        return snapshot
    ids = [UUID(i) for i in assets]
    rows = {
        str(a.id): a
        for a in await session.scalars(select(MediaAsset).where(MediaAsset.tenant_id == site.tenant_id, MediaAsset.id.in_(ids)))
    }
    private = await tenant_store(site.tenant_id)
    scope = site_scope(site.id)
    gate = asyncio.Semaphore(_CONCURRENCY)

    async def copy(key: str, ext: str, content_type: str, sha256: str | None) -> str:
        async def load() -> bytes:
            blob = await private.get(key)
            if blob is None:
                raise FileNotFoundError(key)
            return blob.body

        async with gate:
            return (await store.publish(site.tenant_id, scope, ext=ext, content_type=content_type, load=load, sha256=sha256)).url

    async def one(asset_id: str, asset: MediaAsset) -> tuple[str, dict[str, Any]]:
        original = copy(asset.key, asset.ext, asset.mime, asset.checksum)
        names = [n for n, v in (asset.variants or {}).items() if isinstance(v, dict) and v.get('key')]
        variants = [
            copy(v['key'], v['format'], f'image/{v["format"]}', v.get('sha256'))
            for v in (asset.variants[n] for n in names)
        ]
        urls = await asyncio.gather(original, *variants)
        return asset_id, {'original': urls[0], 'variants': dict(zip(names, urls[1:], strict=True))}

    try:
        results = await asyncio.gather(*(one(i, rows[i]) for i in assets if i in rows))
    except Exception as error:
        logger.exception('CDN copy failed for site %s', site.id)
        raise ServiceUnavailableException(detail='the media could not be copied to the CDN; try again') from error
    for asset_id, public in results:
        assets[asset_id] = {**assets[asset_id], 'public': public}
    snapshot['cdn_origin'] = _origin(store.base_url)
    return snapshot


async def remove_site_media(site: Site) -> None:
    """Unpublish / archive / delete: drop the site's public copies (best effort, logged)."""
    store = public_store()
    if store is None:
        return
    try:
        deleted = await store.delete_scope(site.tenant_id, site_scope(site.id))
        logger.info('removed %s public objects of site %s', deleted, site.id)
    except Exception:
        logger.exception('could not remove the public objects of site %s', site.id)
