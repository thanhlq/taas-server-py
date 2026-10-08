"""Public CDN copies of a site's media (taas-specs/platform/storage §3, content ADR C-2).

Publishing a release copies every file of the referenced media (original + variants) to the shared public bucket
under ``{tenantId}/site/{siteId}/{sha256}.{ext}`` and writes the CDN URLs into the release snapshot
(``assets[id].public``, ``cdn_origin``). Unpublish / archive / delete remove the site's prefix; rollback and restore
copy again whatever is missing. Previews never touch the public bucket. The mechanics are shared with the other
publishing apps: ``ews.media._publishing``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from db.models.sites import Site
from foundation.db.types import DBAsyncScopedSession

from ews.media._publishing import (  # noqa: F401 (re-exported for the sites code and tests)
    public_store,
    publish_assets,
    remove_public_scope,
    use_public_store,
)


def site_scope(site_id: UUID | str) -> str:
    return f'site/{site_id}'


async def publish_snapshot_media(
    session: DBAsyncScopedSession, site: Site, snapshot: dict[str, Any]
) -> dict[str, Any]:
    """Copy the media of ``snapshot`` to the CDN and return it with public URLs (unchanged without a CDN)."""
    assets, origin = await publish_assets(
        session, site.tenant_id, site_scope(site.id), snapshot.get('assets') or {}
    )
    if assets:
        snapshot['assets'] = assets
    snapshot['cdn_origin'] = origin
    return snapshot


async def remove_site_media(site: Site) -> None:
    """Unpublish / archive / delete: drop the site's public copies (best effort, logged)."""
    await remove_public_scope(site.tenant_id, site_scope(site.id))
