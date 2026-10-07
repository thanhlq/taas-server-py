"""Publishing (editor-spec §6, routing-hosting-spec §2 / §4).

A **release** is an immutable, self-contained snapshot of the whole site (pages + theme + menus +
redirects + media metadata): the renderer serves it without querying anything else, so live sites keep
working when the editor / API is down. Rollback = a new release with an older snapshot.
"""

from __future__ import annotations

import copy
import hashlib
import json
import uuid
from datetime import timedelta
from typing import Any
from uuid import UUID

from db.models.media import MediaAsset
from db.models.sites import Site, SiteMenu, SitePage, SitePageRevision, SiteRedirect, SiteRelease
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException, NotFoundException
from sqlalchemy import func, select, text

from ews.security import RequestScope
from ews.shared import parse_uuid, sign_token, utcnow, verify_token

from ._audit import audit
from ._cdn import publish_snapshot_media, remove_site_media
from ._document import asset_ids, migrate_document
from ._rules import accessibility_issues
from ._service import ConflictException, site_pages, user_names
from ._settings import sites_settings
from .schemas import AccessibilityIssueOut, ChangeOut, ReleaseOut, RouteOut

SNAPSHOT_FORMAT = 1
PREVIEW_PURPOSE = 'sites.preview'


# --- snapshot -------------------------------------------------------------------------------------


async def _org_slug(session: DBAsyncScopedSession, organization_id: UUID) -> str:
    return await session.scalar(text('select slug from taas_organizations where id = :id'), {'id': organization_id}) or ''


def _menu_hrefs(items: list[dict[str, Any]], paths: dict[str, str]) -> list[dict[str, Any]]:
    out = []
    for item in items:
        href = paths.get(item.get('page_id') or '') if item.get('page_id') else item.get('url')
        if item.get('page_id') and href is None:
            continue  # page removed / not published
        entry: dict[str, Any] = {'label': item['label'], 'href': href}
        if item.get('page_id'):
            entry['page_id'] = item['page_id']
        if item.get('children'):
            entry['children'] = _menu_hrefs(item['children'], paths)
        out.append(entry)
    return out


async def _assets(session: DBAsyncScopedSession, tenant_id: UUID, ids: set[UUID]) -> dict[str, Any]:
    if not ids:
        return {}
    rows = await session.scalars(select(MediaAsset).where(MediaAsset.tenant_id == tenant_id, MediaAsset.id.in_(ids)))
    return {
        str(a.id): {
            'kind': a.kind, 'mime': a.mime, 'title': a.title, 'alt': a.alt, 'width': a.width, 'height': a.height,
            'focal_x': a.focal_x, 'focal_y': a.focal_y, 'version': a.key.rsplit('/', 2)[-2] if '/' in a.key else '',
            'variants': {
                name: {'width': v.get('width'), 'height': v.get('height'), 'format': v.get('format')}
                for name, v in (a.variants or {}).items() if isinstance(v, dict)
            },
        }
        for a in rows
    }


async def build_snapshot(
    session: DBAsyncScopedSession,
    site: Site,
    pages: list[tuple[SitePage, SitePageRevision]],
) -> dict[str, Any]:
    """The renderer's view of the site for ``pages`` (page + the revision to show)."""
    menus = {m.key: m.items for m in await session.scalars(select(SiteMenu).where(SiteMenu.site_id == site.id))}
    redirects = list(await session.scalars(select(SiteRedirect).where(SiteRedirect.site_id == site.id)))
    included = {p.id for p, _ in pages}
    paths = {str(p.id): ('/' if p.id == site.home_page_id else p.path) for p, _ in pages}
    refs: set[UUID] = set()
    out_pages = []
    for page, revision in pages:
        doc = migrate_document(revision.doc)
        seo = revision.seo or page.seo or {}
        refs |= asset_ids(doc, seo.get('og_image'))
        out_pages.append({
            'id': str(page.id),
            'parent_id': str(page.parent_id) if page.parent_id and page.parent_id in included else None,
            'path': paths[str(page.id)],
            'title': revision.title or page.title,
            'seo': seo,
            'noindex': page.noindex or page.id == site.not_found_page_id,
            'in_menu': page.in_menu,
            'revision_id': str(revision.id),
            'doc': doc,
        })
    theme = site.theme or {}
    logo = (theme.get('header') or {}).get('logo')
    og_default = ((site.settings or {}).get('seo') or {}).get('og_image')
    for ref in (logo, og_default):
        if isinstance(ref, str) and ref.startswith('asset:'):
            refs.add(UUID(ref[6:]))
    home = next((p for p, _ in pages if p.id == site.home_page_id), None)
    return {
        'format': SNAPSHOT_FORMAT,
        'site': {
            'id': str(site.id),
            'tenant_id': str(site.tenant_id),
            'organization_id': str(site.organization_id),
            'organization_slug': await _org_slug(session, site.organization_id),
            'slug': site.slug,
            'name': site.name,
            'description': site.description,
            'is_root': site.is_root,
            'default_locale': site.default_locale,
            'settings': {k: v for k, v in (site.settings or {}).items() if k in ('seo',)},
        },
        'theme': theme,
        'menus': {key: _menu_hrefs(items, paths) for key, items in menus.items()},
        'pages': out_pages,
        'page_paths': paths,
        'home_page_id': str(site.home_page_id) if site.home_page_id in included else None,
        'not_found_page_id': str(site.not_found_page_id) if site.not_found_page_id in included else None,
        'redirects': [
            {'from': r.from_path, 'to': r.to, 'status': r.status_code}
            for r in redirects
            if not (home and r.from_path == '/')
        ],
        'assets': await _assets(session, site.tenant_id, refs),
        'built_at': utcnow().isoformat(),
    }


async def _drafts(session: DBAsyncScopedSession, pages: list[SitePage]) -> dict[UUID, SitePageRevision]:
    ids = {i for p in pages for i in (p.draft_revision_id, p.published_revision_id) if i}
    if not ids:
        return {}
    return {r.id: r for r in await session.scalars(select(SitePageRevision).where(SitePageRevision.id.in_(ids)))}


async def live_snapshot(session: DBAsyncScopedSession, site: Site) -> dict[str, Any] | None:
    if site.live_release_id is None:
        return None
    return await session.scalar(select(SiteRelease.snapshot).where(SiteRelease.id == site.live_release_id))


# --- changes / accessibility ----------------------------------------------------------------------


async def pending_changes(session: DBAsyncScopedSession, site: Site) -> list[ChangeOut]:
    pages = await site_pages(session, site)
    live = await live_snapshot(session, site)
    changes: list[ChangeOut] = []
    for p in pages:
        if p.published_revision_id is None or live is None:
            changes.append(ChangeOut(kind='page_added', page_id=str(p.id), title=p.title, path=p.path))
        elif p.draft_revision_id != p.published_revision_id:
            changes.append(ChangeOut(kind='page_changed', page_id=str(p.id), title=p.title, path=p.path))
    if live is not None:
        current = {str(p.id) for p in pages}
        for lp in live.get('pages') or []:
            if lp['id'] not in current:
                changes.append(ChangeOut(kind='page_removed', page_id=lp['id'], title=lp['title'], path=lp['path']))
        if (live.get('theme') or {}) != (site.theme or {}):
            changes.append(ChangeOut(kind='theme'))
        menus = {m.key: m.items for m in await session.scalars(select(SiteMenu).where(SiteMenu.site_id == site.id))}
        live_menus = {k: [_strip_hrefs(i) for i in v] for k, v in (live.get('menus') or {}).items()}
        if {k: [_strip_hrefs(i) for i in v] for k, v in menus.items() if v} != {k: v for k, v in live_menus.items() if v}:
            changes.append(ChangeOut(kind='menus'))
        redirects = sorted(
            (r.from_path, r.to, r.status_code) for r in await session.scalars(select(SiteRedirect).where(SiteRedirect.site_id == site.id))
        )
        if redirects != sorted((r['from'], r['to'], r['status']) for r in live.get('redirects') or []):
            changes.append(ChangeOut(kind='redirects'))
        if (live.get('site') or {}).get('settings', {}).get('seo') != (site.settings or {}).get('seo'):
            changes.append(ChangeOut(kind='settings'))
    return changes


def _strip_hrefs(item: dict[str, Any]) -> dict[str, Any]:
    out = {'label': item.get('label')}
    if item.get('page_id'):
        out['page_id'] = item['page_id']
    elif item.get('url') or item.get('href'):
        out['url'] = item.get('url') or item.get('href')
    if item.get('children'):
        out['children'] = [_strip_hrefs(c) for c in item['children']]
    return out


async def check_accessibility(
    session: DBAsyncScopedSession, site: Site, pages: list[tuple[SitePage, SitePageRevision]]
) -> list[AccessibilityIssueOut]:
    refs: set[UUID] = set()
    for _, r in pages:
        refs |= asset_ids(r.doc)
    alts: dict[str, str | None] = {}
    if refs:
        for a in await session.scalars(select(MediaAsset).where(MediaAsset.id.in_(refs))):
            alts[f'asset:{a.id}'] = a.alt
    out: list[AccessibilityIssueOut] = []
    for page, revision in pages:
        for issue in accessibility_issues(revision.doc, asset_alts=alts, page_id=str(page.id)):
            out.append(AccessibilityIssueOut(
                severity=issue.severity, code=issue.code, message=issue.message, page_id=issue.page_id,
                page_title=page.title, block_id=issue.block_id,
            ))
    from ._rules import theme_contrast_issues

    for issue in theme_contrast_issues(site.theme or {}):
        out.append(AccessibilityIssueOut(severity=issue.severity, code=issue.code, message=issue.message))
    return out


async def draft_pages(session: DBAsyncScopedSession, site: Site) -> list[tuple[SitePage, SitePageRevision]]:
    pages = await site_pages(session, site)
    revisions = await _drafts(session, pages)
    return [(p, revisions[p.draft_revision_id]) for p in pages if p.draft_revision_id in revisions]


# --- publish / rollback ---------------------------------------------------------------------------


async def publish(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    site: Site,
    *,
    page_ids: list[str] | None = None,
    note: str | None = None,
    ignore_accessibility: bool = False,
) -> SiteRelease:
    if site.status == 'archived':
        raise ClientException(detail='restore the site before publishing it')
    pages = await site_pages(session, site)
    revisions = await _drafts(session, pages)
    selected = {parse_uuid(i, 'page', not_found=False) for i in page_ids} if page_ids is not None else None
    if selected is not None and not selected <= {p.id for p in pages}:
        raise ClientException(detail='unknown page in page_ids')
    chosen: list[tuple[SitePage, SitePageRevision]] = []
    for p in pages:
        use_draft = selected is None or p.id in selected
        rid = p.draft_revision_id if use_draft else p.published_revision_id
        if rid in revisions:
            chosen.append((p, revisions[rid]))
    if site.home_page_id not in {p.id for p, _ in chosen}:
        raise ClientException(detail='publish the home page too: a site needs its home page')
    to_check = [(p, r) for p, r in chosen if selected is None or p.id in selected]
    issues = await check_accessibility(session, site, to_check)
    blocking = [i for i in issues if i.severity == 'error']
    if blocking and not ignore_accessibility:
        raise ConflictException(
            detail=f'{len(blocking)} accessibility error(s): fix them or publish anyway',
            extra={'code': 'accessibility', 'issues': [{'message': i.message, 'page_id': i.page_id, 'block_id': i.block_id} for i in blocking]},
        )
    changes = [c.as_dict() for c in await pending_changes(session, site)]
    if selected is not None:
        changes = [c for c in changes if c.get('page_id') is None or UUID(c['page_id']) in selected or c['kind'] == 'page_removed']
    snapshot = await publish_snapshot_media(session, site, await build_snapshot(session, site, chosen))
    number = (await session.scalar(select(func.max(SiteRelease.number)).where(SiteRelease.site_id == site.id)) or 0) + 1
    release = SiteRelease(
        id=uuid.uuid7(), tenant_id=site.tenant_id, site_id=site.id, number=number, snapshot=snapshot, changes=changes,
        note=(note or '').strip()[:500] or None, published_by=scope.user_id, published_at=utcnow(),
    )
    session.add(release)
    for page, revision in chosen:
        page.published_revision_id = revision.id
    site.live_release_id, site.status, site.published_at = release.id, 'published', release.published_at
    audit(session, scope, 'site.published', site_id=site.id, target_type='release', target_id=release.id,
          number=number, pages=len(chosen), partial=selected is not None, accessibility_ignored=bool(blocking))
    await session.flush()
    return release


async def release_out(session: DBAsyncScopedSession, site: Site, releases: list[SiteRelease]) -> list[ReleaseOut]:
    names = await user_names(session, [r.published_by for r in releases])
    return [
        ReleaseOut(
            id=str(r.id), number=r.number, note=r.note, changes=r.changes or [], page_count=len((r.snapshot or {}).get('pages') or []),
            published_by=str(r.published_by) if r.published_by else None, published_by_name=names.get(r.published_by) if r.published_by else None,
            published_at=r.published_at, is_live=r.id == site.live_release_id, rollback_of=str(r.rollback_of) if r.rollback_of else None,
        )
        for r in releases
    ]


async def list_releases(session: DBAsyncScopedSession, site: Site, limit: int = 50) -> list[ReleaseOut]:
    rows = list(
        await session.scalars(
            select(SiteRelease).where(SiteRelease.site_id == site.id).order_by(SiteRelease.number.desc()).limit(min(limit, 200))
        )
    )
    return await release_out(session, site, rows)


async def rollback(session: DBAsyncScopedSession, scope: RequestScope, site: Site, release_id: object) -> SiteRelease:
    rid = parse_uuid(release_id, 'release')
    target = await session.scalar(select(SiteRelease).where(SiteRelease.id == rid, SiteRelease.site_id == site.id))
    if target is None:
        raise NotFoundException(detail='release not found')
    if target.id == site.live_release_id:
        raise ClientException(detail='this release is already live')
    number = (await session.scalar(select(func.max(SiteRelease.number)).where(SiteRelease.site_id == site.id)) or 0) + 1
    # copies removed by an unpublish are made again (the public bucket can be rebuilt, Sto-0003)
    snapshot = await publish_snapshot_media(session, site, copy.deepcopy(target.snapshot or {}))
    release = SiteRelease(
        id=uuid.uuid7(), tenant_id=site.tenant_id, site_id=site.id, number=number, snapshot=snapshot,
        changes=[{'kind': 'rollback', 'title': f'Rollback to release {target.number}'}],
        note=f'Rollback to release {target.number}', published_by=scope.user_id, published_at=utcnow(), rollback_of=target.id,
    )
    session.add(release)
    revision_of = {UUID(p['id']): UUID(p['revision_id']) for p in (target.snapshot or {}).get('pages') or []}
    for page in await site_pages(session, site):
        page.published_revision_id = revision_of.get(page.id)
    site.live_release_id, site.status, site.published_at = release.id, 'published', release.published_at
    audit(session, scope, 'site.rolled_back', site_id=site.id, target_type='release', target_id=release.id, to_number=target.number)
    await session.flush()
    return release


async def unpublish(session: DBAsyncScopedSession, scope: RequestScope, site: Site) -> None:
    site.live_release_id, site.status = None, 'draft'
    for page in await site_pages(session, site):
        page.published_revision_id = None
    audit(session, scope, 'site.unpublished', site_id=site.id, target_type='site', target_id=site.id)
    await session.flush()
    await remove_site_media(site)


# --- preview links (Site-0505) --------------------------------------------------------------------


def preview_url(org_slug: str, token: str, path: str = '/') -> str:
    return sites_settings().public_url(org_slug, f'/_preview/{token}{path}')


async def create_preview_link(
    session: DBAsyncScopedSession, scope: RequestScope, site: Site, *, page_id: str | None, days: int
) -> tuple[str, Any]:
    days = max(1, min(days, sites_settings().preview_max_days))
    expires = utcnow() + timedelta(days=days)
    path = '/'
    if page_id:
        from ._service import get_page

        page = await get_page(session, site, page_id)
        path = '/' if page.id == site.home_page_id else page.path
    token = sign_token({'s': str(site.id), 'v': site.preview_version, 'exp': int(expires.timestamp())}, purpose=PREVIEW_PURPOSE)
    audit(session, scope, 'preview.created', site_id=site.id, target_type='site', target_id=site.id, days=days)
    return preview_url(scope.organization.slug, token, path), expires


async def revoke_preview_links(session: DBAsyncScopedSession, scope: RequestScope, site: Site) -> None:
    site.preview_version += 1
    audit(session, scope, 'preview.revoked', site_id=site.id, target_type='site', target_id=site.id)
    await session.flush()


async def preview_snapshot(session: DBAsyncScopedSession, token: str) -> dict[str, Any]:
    claims = verify_token(token, purpose=PREVIEW_PURPOSE)
    if not claims:
        raise NotFoundException(detail='preview link expired or invalid')
    site = await session.scalar(select(Site).where(Site.id == UUID(claims['s']), Site.deleted_at.is_(None)))
    if site is None or site.preview_version != claims.get('v'):
        raise NotFoundException(detail='preview link expired or invalid')
    snapshot = await build_snapshot(session, site, await draft_pages(session, site))
    snapshot['preview'] = {'expires_at': claims['exp']}
    return snapshot


# --- routing table (Site-0610 / 0611) -------------------------------------------------------------


async def routing_table(session: DBAsyncScopedSession) -> tuple[str, list[RouteOut]]:
    """Every live system route of the platform: ``<org-slug>.<SITES_DOMAIN>`` + ``/<site-slug>`` (or ``/``)."""
    settings = sites_settings()
    rows = await session.execute(
        text(
            'select s.id, s.tenant_id, s.slug, s.is_root, s.live_release_id, o.slug as org_slug '
            'from taas_site_sites s join taas_organizations o on o.id = s.organization_id '
            "where s.deleted_at is null and s.status = 'published' and s.live_release_id is not null "
            'order by o.slug, s.slug'
        )
    )
    routes = [
        RouteOut(
            host=settings.org_host(r.org_slug),
            prefix='/' if r.is_root else f'/{r.slug}',
            site_id=str(r.id),
            tenant_id=str(r.tenant_id),
            release_id=str(r.live_release_id),
        )
        for r in rows
    ]
    digest = hashlib.sha1(json.dumps([r.as_dict() for r in routes], sort_keys=True).encode()).hexdigest()[:16]
    return digest, routes


async def release_snapshot(session: DBAsyncScopedSession, release_id: object) -> dict[str, Any]:
    rid = parse_uuid(release_id, 'release')
    snapshot = await session.scalar(select(SiteRelease.snapshot).where(SiteRelease.id == rid))
    if snapshot is None:
        raise NotFoundException(detail='release not found')
    return snapshot

