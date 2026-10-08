"""``/api/v1/sites-internal`` — read API of the site renderer (routing-hosting-spec §2 / §4).

Authenticated by the renderer's shared secret (``X-Sites-Renderer-Key`` = ``SITES_RENDERER_KEY``), never
by user sessions; serve it on the internal network only (the public reverse proxy must not route it).
"""

from __future__ import annotations

import hmac
from typing import Any

from db.models.media import MediaAsset
from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import NotAuthorizedException, NotFoundException, ServiceUnavailableException
from foundation.http import BaseController, get, post
from foundation.http.context import Context
from sqlalchemy import select

from ews.media._service import tenant_store
from ews.shared import parse_uuid, raw_response

from .. import _forms as forms
from .. import _publish as pub
from .._settings import sites_settings
from ..schemas import FormSubmit, FormSubmitOut, RoutesOut, SnapshotOut


def require_renderer(ctx: Context) -> None:
    """401 unless the request carries the renderer key (503 when none is configured). Shared by every
    ``/api/v1/sites-internal`` controller (sites, blogs)."""
    expected = sites_settings().renderer_key
    if not expected:
        raise ServiceUnavailableException(detail='SITES_RENDERER_KEY is not configured')
    given = ctx.req.headers.get('x-sites-renderer-key') or ''
    if not hmac.compare_digest(given.encode(), expected.encode()):
        raise NotAuthorizedException(detail='invalid renderer key')


class SitesInternalController(BaseController):
    api_prefix = '/api/v1/sites-internal'
    tags = ('Site Builder (renderer)',)

    @get('/routes', summary='Routing table: host + path prefix → site, live release')
    @db_context_session
    async def routes(self, ctx: Context, session: DBAsyncScopedSession) -> RoutesOut:
        require_renderer(ctx)
        version, routes = await pub.routing_table(session)
        return RoutesOut(version=version, sites_domain=sites_settings().domain, routes=routes)

    @get('/releases/{release_id}', summary='Release snapshot (immutable: cache forever)')
    @db_context_session
    async def release(self, release_id: str, ctx: Context, session: DBAsyncScopedSession) -> SnapshotOut:
        require_renderer(ctx)
        return SnapshotOut(release_id=release_id, snapshot=await pub.release_snapshot(session, release_id))

    @get('/preview/{token}', summary='Draft snapshot behind a signed preview link')
    @db_context_session
    async def preview(self, token: str, ctx: Context, session: DBAsyncScopedSession) -> SnapshotOut:
        require_renderer(ctx)
        return SnapshotOut(snapshot=await pub.preview_snapshot(session, token))

    @get('/assets/{tenant_id}/{asset_id}/{name}', summary='Media bytes (original or a variant) for /_assets')
    @db_context_session
    async def asset(self, tenant_id: str, asset_id: str, name: str, ctx: Context, session: DBAsyncScopedSession) -> Any:
        require_renderer(ctx)
        asset = await session.scalar(
            select(MediaAsset).where(
                MediaAsset.id == parse_uuid(asset_id, 'asset'), MediaAsset.tenant_id == parse_uuid(tenant_id, 'tenant')
            )
        )
        if asset is None:
            raise NotFoundException(detail='asset not found')
        if name == 'original':
            key, mime = asset.key, asset.mime
        else:
            variant = (asset.variants or {}).get(name)
            if not isinstance(variant, dict):
                raise NotFoundException(detail='variant not found')
            key, mime = variant['key'], f'image/{variant["format"]}'
        blob = await (await tenant_store(asset.tenant_id)).get(key)
        if blob is None:
            raise NotFoundException(detail='file not found')
        return raw_response(blob.body, media_type=mime, request=ctx.req, headers={'cache-control': 'public, max-age=31536000, immutable'})

    @post('/forms/{site_id}/{form_key}', summary='A visitor submitted a form (forwarded by the renderer)')
    @db_context_session(auto_commit=True)
    async def submit_form(self, site_id: str, form_key: str, data: FormSubmit, ctx: Context, session: DBAsyncScopedSession) -> FormSubmitOut:
        require_renderer(ctx)
        ok, message = await forms.submit(
            session, site_id, form_key, data.data, page_id=data.page_id, ip_hash=data.ip_hash, honeypot=data.honeypot
        )
        return FormSubmitOut(ok=ok, message=message)
