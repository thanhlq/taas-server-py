"""Sites, page tree, drafts / revisions, soft locks, menus, redirects, theme, export / import.

``session`` = the request's DB session (``db_context_session``), ``scope`` = the verified caller.
Publishing lives in ``_publish``, members in ``_members``, forms in ``_forms``, AI in ``_ai``.
"""

from __future__ import annotations

import copy
import re
import uuid
from collections.abc import Iterable
from dataclasses import asdict
from datetime import timedelta
from typing import Any
from uuid import UUID

import msgspec
from db.models.sites import Site, SiteMenu, SitePage, SitePageRevision, SiteRedirect, SiteRelease
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException, NotFoundException, ValidationException
from sqlalchemy import func, select, text

from ews.authz import SiteRoles, grant, revoke_domain
from ews.media import record_usages
from ews.security import RequestScope, is_allowed
from ews.shared import parse_uuid, utcnow

from . import _access as access
from ._audit import audit
from ._cdn import publish_snapshot_media, remove_site_media
from ._document import asset_ids, empty_document, migrate_document, validate_document
from ._rules import (
    MAX_PAGE_DEPTH,
    MENU_KEYS,
    creates_loop,
    normalize_menu,
    normalize_theme,
    page_path,
    page_slug_error,
    site_slug_error,
    slugify,
    theme_contrast_issues,
)
from ._settings import SitesSettings, sites_settings
from ._templates import get_template
from .schemas import (
    MenuOut,
    PageCreate,
    PageDetailOut,
    PageOut,
    PageUpdate,
    RedirectOut,
    RevisionDetailOut,
    RevisionOut,
    SiteCreate,
    SiteOut,
    SiteUpdate,
)

LOCK_TTL = timedelta(seconds=120)
REVISION_WINDOW = timedelta(seconds=60)
"""Autosaves of the same author within this window update the working draft (Site-0204)."""


class ConflictException(ClientException):
    status_code = 409


def _invalid(issues: Iterable[Any], what: str = 'document') -> ValidationException:
    items = [str(i) for i in issues]
    return ValidationException(detail=f'invalid {what}: {items[0] if items else ""}', extra={'issues': items})


# --- users ----------------------------------------------------------------------------------------


async def user_names(session: DBAsyncScopedSession, ids: Iterable[UUID | None]) -> dict[UUID, str]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    rows = await session.execute(
        text('select id, coalesce(nullif(name, \'\'), email) as label from taas_user_account where id = any(:ids)'),
        {'ids': list(wanted)},
    )
    return {r.id: r.label for r in rows}


# --- sites ----------------------------------------------------------------------------------------


def site_url(scope: RequestScope, site: Site, settings: SitesSettings | None = None) -> str:
    settings = settings or sites_settings()
    return settings.public_url(scope.organization.slug, '/' if site.is_root else f'/{site.slug}/')


async def _page_status_counts(session: DBAsyncScopedSession, site_ids: list[UUID]) -> dict[UUID, tuple[int, int]]:
    """``{site_id: (pages, pages with unpublished changes)}``."""
    if not site_ids:
        return {}
    rows = await session.execute(
        select(
            SitePage.site_id,
            func.count(),
            func.count().filter(SitePage.draft_revision_id.is_distinct_from(SitePage.published_revision_id)),
        )
        .where(SitePage.site_id.in_(site_ids), SitePage.deleted_at.is_(None))
        .group_by(SitePage.site_id)
    )
    return {sid: (total, changed) for sid, total, changed in rows.all()}


async def site_out(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    site: Site,
    *,
    counts: tuple[int, int] | None = None,
    release_number: int | None = None,
) -> SiteOut:
    if counts is None:
        counts = (await _page_status_counts(session, [site.id])).get(site.id, (0, 0))
    if release_number is None and site.live_release_id:
        release_number = await session.scalar(select(SiteRelease.number).where(SiteRelease.id == site.live_release_id))
    return SiteOut(
        id=str(site.id),
        slug=site.slug,
        name=site.name,
        description=site.description,
        status=site.status,
        is_root=site.is_root,
        default_locale=site.default_locale,
        template=site.template,
        url=site_url(scope, site),
        home_page_id=str(site.home_page_id) if site.home_page_id else None,
        not_found_page_id=str(site.not_found_page_id) if site.not_found_page_id else None,
        theme=site.theme or {},
        settings=site.settings or {},
        live_release_id=str(site.live_release_id) if site.live_release_id else None,
        live_release_number=release_number,
        published_at=site.published_at,
        page_count=counts[0],
        pending_changes=counts[1],
        role=await access.role_on(scope, site.id),
        permissions=sorted(await access.permissions_on(scope, site.id)),
        created_at=site.created_at,
        updated_at=site.updated_at,
    )


async def list_sites(session: DBAsyncScopedSession, scope: RequestScope, *, include_archived: bool = True) -> list[SiteOut]:
    readable = await access.readable_site_ids(scope)
    stmt = select(Site).where(
        Site.tenant_id == scope.tenant_id,
        Site.organization_id == scope.organization_id,
        Site.deleted_at.is_(None),
    )
    if readable is not None:
        if not readable:
            return []
        stmt = stmt.where(Site.id.in_(readable))
    if not include_archived:
        stmt = stmt.where(Site.status != 'archived')
    sites = list(await session.scalars(stmt.order_by(Site.updated_at.desc())))
    counts = await _page_status_counts(session, [s.id for s in sites])
    numbers = dict(
        (
            await session.execute(
                select(SiteRelease.id, SiteRelease.number).where(
                    SiteRelease.id.in_([s.live_release_id for s in sites if s.live_release_id])
                )
            )
        ).all()
    )
    return [
        await site_out(session, scope, s, counts=counts.get(s.id, (0, 0)), release_number=numbers.get(s.live_release_id))
        for s in sites
    ]


async def _slug_taken(session: DBAsyncScopedSession, scope: RequestScope, slug: str, exclude: UUID | None = None) -> bool:
    stmt = select(Site.id).where(
        Site.organization_id == scope.organization_id, Site.slug == slug, Site.deleted_at.is_(None)
    )
    if exclude:
        stmt = stmt.where(Site.id != exclude)
    return (await session.scalar(stmt)) is not None


async def _free_slug(session: DBAsyncScopedSession, scope: RequestScope, base: str) -> str:
    base = (slugify(base) or 'site')[:36].strip('-')
    if len(base) < 2:
        base = f'{base}site'
    slug, n = base, 2
    while await _slug_taken(session, scope, slug):
        slug, n = f'{base}-{n}', n + 1
    return slug


async def _clear_root(session: DBAsyncScopedSession, scope: RequestScope, except_id: UUID) -> None:
    others = await session.scalars(
        select(Site).where(
            Site.organization_id == scope.organization_id, Site.is_root.is_(True), Site.id != except_id, Site.deleted_at.is_(None)
        )
    )
    for other in others:
        other.is_root = False
    await session.flush()


async def create_site(session: DBAsyncScopedSession, scope: RequestScope, data: SiteCreate) -> Site:
    settings = sites_settings()
    name = (data.name or '').strip()
    if not name or len(name) > 120:
        raise ClientException(detail='name must be 1 to 120 characters')
    if settings.max_sites:
        count = await session.scalar(
            select(func.count()).where(Site.tenant_id == scope.tenant_id, Site.deleted_at.is_(None))
        )
        if (count or 0) >= settings.max_sites:
            raise ConflictException(detail=f'your plan allows {settings.max_sites} sites', extra={'code': 'plan_limit'})
    if data.slug:
        if error := site_slug_error(data.slug):
            raise ClientException(detail=error)
        if await _slug_taken(session, scope, data.slug):
            raise ConflictException(detail='this slug is already used by another site of the organization')
        slug = data.slug
    else:
        slug = await _free_slug(session, scope, name)
    template = get_template(data.template or 'blank')
    if template is None:
        raise ClientException(detail=f'unknown template {data.template}')
    site = Site(
        id=uuid.uuid7(),
        tenant_id=scope.tenant_id,
        organization_id=scope.organization_id,
        slug=slug,
        name=name,
        description=(data.description or '').strip()[:500] or None,
        status='draft',
        is_root=False,
        template=template['key'],
        theme={},
        settings={'seo': {'title_template': f'%s · {name}'}},
        created_by=scope.user_id,
    )
    session.add(site)
    await session.flush()
    if data.is_root:
        await _clear_root(session, scope, site.id)
        site.is_root = True
    await instantiate(session, scope, site, template, source='template')
    if not scope.is_dev:
        await grant(scope.user_id, SiteRoles.SITE_ADMIN.value, f'site:{site.id}')
    audit(session, scope, 'site.created', site_id=site.id, target_type='site', target_id=site.id, template=template['key'])
    await session.flush()
    return site


def _remap_refs(value: Any, mapping: dict[str, str]) -> Any:
    """Rewrite ``page:<old id>`` references after an import."""
    if isinstance(value, str):
        m = re.match(r'^page:([0-9a-fA-F-]{36})(#.*)?$', value)
        return f'page:{mapping[m.group(1)]}{m.group(2) or ""}' if m and m.group(1) in mapping else value
    if isinstance(value, dict):
        return {k: _remap_refs(v, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [_remap_refs(v, mapping) for v in value]
    return value


async def instantiate(
    session: DBAsyncScopedSession, scope: RequestScope, site: Site, shape: dict[str, Any], *, source: str
) -> None:
    """Create theme, pages (+ draft revisions) and menus from a template / export shape."""
    theme, errors = normalize_theme(shape.get('theme') or {})
    if errors:
        raise _invalid(errors, 'theme')
    site.theme = theme
    pages = shape.get('pages') or []
    keys: dict[str, SitePage] = {}
    mapping: dict[str, str] = {}
    now = utcnow()
    for position, spec in enumerate(pages):
        page_id = uuid.uuid7()
        mapping[str(spec.get('key'))] = str(page_id)
    for position, spec in enumerate(pages):
        slug = spec.get('slug') or slugify(spec.get('title') or 'page', 80) or 'page'
        if error := page_slug_error(slug):
            raise ClientException(detail=f'page {spec.get("title")}: {error}')
        parent = keys.get(str(spec.get('parent'))) if spec.get('parent') else None
        doc = _remap_refs(copy.deepcopy(spec.get('doc') or empty_document()), mapping)
        if issues := validate_document(doc):
            raise _invalid(issues)
        page = SitePage(
            id=UUID(mapping[str(spec.get('key'))]),
            tenant_id=site.tenant_id,
            site_id=site.id,
            parent_id=parent.id if parent else None,
            slug=slug,
            path=page_path(parent.path if parent else None, slug),
            locale=site.default_locale,
            title=(spec.get('title') or slug)[:200],
            position=position,
            in_menu=bool(spec.get('in_menu', True)),
            noindex=bool(spec.get('noindex', False)),
            seo=spec.get('seo') or {},
            created_by=scope.user_id,
            updated_by=scope.user_id,
        )
        session.add(page)
        await session.flush()
        revision = SitePageRevision(
            id=uuid.uuid7(),
            tenant_id=site.tenant_id,
            site_id=site.id,
            page_id=page.id,
            doc=doc,
            source=source,
            title=page.title,
            seo=page.seo,
            author_id=scope.user_id,
            created_at=now,
        )
        session.add(revision)
        page.draft_revision_id = revision.id
        keys[str(spec.get('key'))] = page
        if spec.get('home'):
            site.home_page_id = page.id
        if spec.get('not_found'):
            site.not_found_page_id = page.id
        await _record_usages(session, site, page, doc)
    if site.home_page_id is None and keys:
        site.home_page_id = next(iter(keys.values())).id
    for key in MENU_KEYS:
        items = []
        for item in (shape.get('menus') or {}).get(key) or []:
            entry = {k: v for k, v in item.items() if k in ('label', 'url', 'children')}
            if item.get('page') and str(item['page']) in keys:
                entry['page_id'] = str(keys[str(item['page'])].id)
            elif item.get('page_id') and str(item['page_id']) in mapping:
                entry['page_id'] = mapping[str(item['page_id'])]
            items.append(entry)
        clean, menu_errors = normalize_menu(items)
        if menu_errors:
            raise _invalid(menu_errors, 'menu')
        session.add(SiteMenu(tenant_id=site.tenant_id, site_id=site.id, key=key, items=clean))
    for redirect in shape.get('redirects') or []:
        if isinstance(redirect, dict) and redirect.get('from_path') and redirect.get('to'):
            session.add(
                SiteRedirect(
                    tenant_id=site.tenant_id,
                    site_id=site.id,
                    from_path=str(redirect['from_path'])[:512],
                    to=str(redirect['to'])[:1024],
                    status_code=int(redirect.get('status_code') or 301),
                    auto=False,
                )
            )
    await session.flush()


async def update_site(session: DBAsyncScopedSession, scope: RequestScope, site: Site, data: SiteUpdate) -> Site:
    changes: dict[str, Any] = {}
    if data.name is not None:
        name = data.name.strip()
        if not name or len(name) > 120:
            raise ClientException(detail='name must be 1 to 120 characters')
        site.name, changes['name'] = name, name
    if data.slug is not None and data.slug != site.slug:
        if error := site_slug_error(data.slug):
            raise ClientException(detail=error)
        if await _slug_taken(session, scope, data.slug, exclude=site.id):
            raise ConflictException(detail='this slug is already used by another site of the organization')
        changes['slug'] = {'from': site.slug, 'to': data.slug}
        site.slug = data.slug
    if data.description is not None:
        site.description = data.description.strip()[:500] or None
    if data.is_root is not None and data.is_root != site.is_root:
        if data.is_root:
            await _clear_root(session, scope, site.id)
        site.is_root, changes['is_root'] = data.is_root, data.is_root
    if data.default_locale is not None:
        if not re.match(r'^[a-z]{2}(-[A-Z]{2})?$', data.default_locale):
            raise ClientException(detail='default_locale must look like en or pt-BR')
        site.default_locale = data.default_locale
    if data.settings is not None:
        site.settings = _clean_settings(data.settings)
        changes['settings'] = True
    for field in ('home_page_id', 'not_found_page_id'):
        value = getattr(data, field)
        if value is not None:
            page = await get_page(session, site, value)
            setattr(site, field, page.id)
            changes[field] = str(page.id)
    site.updated_at = utcnow()
    audit(session, scope, 'site.updated', site_id=site.id, target_type='site', target_id=site.id, changes=changes)
    await session.flush()
    return site


def _clean_settings(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    seo = raw.get('seo') if isinstance(raw.get('seo'), dict) else {}
    out['seo'] = {
        'title_template': str(seo.get('title_template') or '%s')[:120],
        'description': (str(seo['description'])[:300] if seo.get('description') else None),
        'og_image': seo.get('og_image') if isinstance(seo.get('og_image'), str) and seo['og_image'].startswith('asset:') else None,
    }
    if '%s' not in out['seo']['title_template']:
        raise ClientException(detail='seo.title_template must contain %s (the page title)')
    email = raw.get('notify_email')
    if email:
        if not isinstance(email, str) or not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email) or len(email) > 254:
            raise ClientException(detail='notify_email must be an e-mail address')
        out['notify_email'] = email
    ai = raw.get('ai') if isinstance(raw.get('ai'), dict) else {}
    out['ai'] = {
        'enabled': bool(ai.get('enabled', True)),
        'tone': str(ai.get('tone') or '')[:200] or None,
        'audience': str(ai.get('audience') or '')[:200] or None,
        'words_use': str(ai.get('words_use') or '')[:500] or None,
        'words_avoid': str(ai.get('words_avoid') or '')[:500] or None,
    }
    return out


async def set_status(session: DBAsyncScopedSession, scope: RequestScope, site: Site, status: str) -> Site:
    """Archive (unpublished from the public hosts) or restore a site."""
    if status == 'archived':
        site.status, site.archived_at = 'archived', utcnow()
    else:
        site.status = 'published' if site.live_release_id else 'draft'
        site.archived_at = None
    audit(session, scope, f'site.{"archived" if status == "archived" else "restored"}', site_id=site.id, target_type='site', target_id=site.id)
    await session.flush()
    if status == 'archived':
        await remove_site_media(site)
    elif site.live_release_id:
        live = await session.get(SiteRelease, site.live_release_id)
        if live is not None:  # the copies were removed on archive: copy them again
            live.snapshot = await publish_snapshot_media(session, site, copy.deepcopy(live.snapshot or {}))
            await session.flush()
    return site


async def delete_site(session: DBAsyncScopedSession, scope: RequestScope, site: Site) -> None:
    site.deleted_at = utcnow()
    site.slug = f'{site.slug[:24]}-deleted-{uuid.uuid4().hex[:6]}'[:40]
    site.is_root = False
    audit(session, scope, 'site.deleted', site_id=site.id, target_type='site', target_id=site.id)
    await session.flush()
    await revoke_domain(f'site:{site.id}')
    await remove_site_media(site)


async def set_theme(session: DBAsyncScopedSession, scope: RequestScope, site: Site, raw: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    theme, errors = normalize_theme(raw)
    if errors:
        raise _invalid(errors, 'theme')
    site.theme = theme
    site.updated_at = utcnow()
    logo = theme['header'].get('logo')
    await record_usages(
        session, site.tenant_id, app='sites', ref_type='site_theme', ref_id=site.id, label=f'{site.name} › Theme',
        asset_ids=[UUID(logo[6:])] if logo else [],
    )
    audit(session, scope, 'theme.updated', site_id=site.id, target_type='site', target_id=site.id)
    await session.flush()
    return theme, [asdict(i) for i in theme_contrast_issues(theme)]


# --- pages ----------------------------------------------------------------------------------------


def page_status(page: SitePage) -> str:
    if page.published_revision_id is None:
        return 'draft'
    return 'published' if page.published_revision_id == page.draft_revision_id else 'changed'


def _lock_holder(page: SitePage) -> UUID | None:
    if page.locked_by and page.locked_at and page.locked_at > utcnow() - LOCK_TTL:
        return page.locked_by
    return None


def page_out(site: Site, page: SitePage, names: dict[UUID, str] | None = None) -> PageOut:
    holder = _lock_holder(page)
    return PageOut(
        id=str(page.id),
        site_id=str(page.site_id),
        parent_id=str(page.parent_id) if page.parent_id else None,
        slug=page.slug,
        path=page.path,
        title=page.title,
        position=page.position,
        in_menu=page.in_menu,
        noindex=page.noindex,
        is_home=site.home_page_id == page.id,
        is_not_found=site.not_found_page_id == page.id,
        seo=page.seo or {},
        status=page_status(page),  # type: ignore[arg-type]
        draft_revision_id=str(page.draft_revision_id) if page.draft_revision_id else None,
        published_revision_id=str(page.published_revision_id) if page.published_revision_id else None,
        locked_by=str(holder) if holder else None,
        locked_by_name=(names or {}).get(holder) if holder else None,
        locked_at=page.locked_at if holder else None,
        updated_by=str(page.updated_by) if page.updated_by else None,
        created_at=page.created_at,
        updated_at=page.updated_at,
    )


async def site_pages(session: DBAsyncScopedSession, site: Site) -> list[SitePage]:
    return list(
        await session.scalars(
            select(SitePage)
            .where(SitePage.site_id == site.id, SitePage.deleted_at.is_(None))
            .order_by(SitePage.position, SitePage.created_at)
        )
    )


async def list_pages(session: DBAsyncScopedSession, site: Site) -> list[PageOut]:
    pages = await site_pages(session, site)
    names = await user_names(session, [_lock_holder(p) for p in pages])
    return [page_out(site, p, names) for p in pages]


async def get_page(session: DBAsyncScopedSession, site: Site, page_id: object) -> SitePage:
    pid = parse_uuid(page_id, 'page', not_found=False)
    page = await session.scalar(
        select(SitePage).where(SitePage.id == pid, SitePage.site_id == site.id, SitePage.deleted_at.is_(None))
    )
    if page is None:
        raise NotFoundException(detail='page not found')
    return page


async def _draft(session: DBAsyncScopedSession, page: SitePage) -> SitePageRevision | None:
    if page.draft_revision_id is None:
        return None
    return await session.get(SitePageRevision, page.draft_revision_id)


async def page_detail(session: DBAsyncScopedSession, site: Site, page: SitePage) -> PageDetailOut:
    revision = await _draft(session, page)
    names = await user_names(session, [_lock_holder(page)])
    base = page_out(site, page, names)
    return PageDetailOut(
        **{f: getattr(base, f) for f in base.__struct_fields__},
        doc=migrate_document(revision.doc) if revision else empty_document(),
        revision_created_at=revision.created_at if revision else None,
        revision_source=revision.source if revision else None,
    )


def _depth(pages_by_id: dict[UUID, SitePage], page: SitePage | None) -> int:
    depth = 0
    while page is not None:
        depth += 1
        page = pages_by_id.get(page.parent_id) if page.parent_id else None
    return depth


async def _path_taken(session: DBAsyncScopedSession, site: Site, path: str, exclude: UUID | None = None) -> bool:
    stmt = select(SitePage.id).where(SitePage.site_id == site.id, SitePage.path == path, SitePage.deleted_at.is_(None))
    if exclude:
        stmt = stmt.where(SitePage.id != exclude)
    return (await session.scalar(stmt)) is not None


async def _record_usages(session: DBAsyncScopedSession, site: Site, page: SitePage, doc: dict[str, Any]) -> None:
    og = (page.seo or {}).get('og_image')
    await record_usages(
        session,
        site.tenant_id,
        app='sites',
        ref_type='page',
        ref_id=page.id,
        label=f'{site.name} › {page.title}',
        asset_ids=asset_ids(doc, og),
    )


async def create_page(session: DBAsyncScopedSession, scope: RequestScope, site: Site, data: PageCreate) -> SitePage:
    settings = sites_settings()
    title = (data.title or '').strip()
    if not title or len(title) > 200:
        raise ClientException(detail='title must be 1 to 200 characters')
    pages = await site_pages(session, site)
    if settings.max_pages and len(pages) >= settings.max_pages:
        raise ConflictException(detail=f'your plan allows {settings.max_pages} pages per site', extra={'code': 'plan_limit'})
    by_id = {p.id: p for p in pages}
    parent = by_id.get(parse_uuid(data.parent_id, 'parent page', not_found=False)) if data.parent_id else None
    if data.parent_id and parent is None:
        raise ClientException(detail='parent page not found')
    if _depth(by_id, parent) >= MAX_PAGE_DEPTH:
        raise ClientException(detail=f'pages nest at most {MAX_PAGE_DEPTH} levels')
    slug = data.slug or slugify(title, 80) or 'page'
    if error := page_slug_error(slug):
        raise ClientException(detail=error)
    path = page_path(parent.path if parent else None, slug)
    if await _path_taken(session, site, path):
        if data.slug:
            raise ConflictException(detail=f'a page already uses {path}')
        n = 2
        while await _path_taken(session, site, page_path(parent.path if parent else None, f'{slug}-{n}')):
            n += 1
        slug = f'{slug}-{n}'
        path = page_path(parent.path if parent else None, slug)
    doc = empty_document()
    if data.copy_of:
        source = await _draft(session, await get_page(session, site, data.copy_of))
        doc = copy.deepcopy(source.doc) if source else doc
    elif data.doc is not None:
        doc = data.doc
    if issues := validate_document(doc):
        raise _invalid(issues)
    siblings = [p for p in pages if p.parent_id == (parent.id if parent else None)]
    page = SitePage(
        id=uuid.uuid7(),
        tenant_id=site.tenant_id,
        site_id=site.id,
        parent_id=parent.id if parent else None,
        slug=slug,
        path=path,
        locale=site.default_locale,
        title=title,
        position=max((p.position for p in siblings), default=-1) + 1,
        in_menu=data.in_menu,
        seo={},
        created_by=scope.user_id,
        updated_by=scope.user_id,
    )
    session.add(page)
    await session.flush()
    revision = SitePageRevision(
        id=uuid.uuid7(), tenant_id=site.tenant_id, site_id=site.id, page_id=page.id, doc=doc,
        source='visual', title=title, seo={}, author_id=scope.user_id, created_at=utcnow(),
    )
    session.add(revision)
    page.draft_revision_id = revision.id
    await _record_usages(session, site, page, doc)
    site.updated_at = utcnow()
    audit(session, scope, 'page.created', site_id=site.id, target_type='page', target_id=page.id, title=title, path=path)
    await session.flush()
    return page


async def _move_paths(session: DBAsyncScopedSession, scope: RequestScope, site: Site, page: SitePage, pages: list[SitePage]) -> None:
    """Recompute paths of ``page`` and its descendants; published pages get automatic 301s (Site-0603)."""
    by_parent: dict[UUID | None, list[SitePage]] = {}
    for p in pages:
        by_parent.setdefault(p.parent_id, []).append(p)
    by_id = {p.id: p for p in pages}
    moved: list[tuple[str, str]] = []
    stack = [page]
    while stack:
        current = stack.pop()
        parent = by_id.get(current.parent_id) if current.parent_id else None
        new_path = page_path(parent.path if parent else None, current.slug)
        if new_path != current.path:
            if await _path_taken(session, site, new_path, exclude=current.id):
                raise ConflictException(detail=f'a page already uses {new_path}')
            if current.published_revision_id is not None:
                moved.append((current.path, new_path))
            current.path = new_path
        stack.extend(by_parent.get(current.id, []))
    await session.flush()
    if moved:
        await _auto_redirects(session, site, moved)


async def _auto_redirects(session: DBAsyncScopedSession, site: Site, moved: list[tuple[str, str]]) -> None:
    existing = {r.from_path: r for r in await session.scalars(select(SiteRedirect).where(SiteRedirect.site_id == site.id))}
    for old, new in moved:
        if new in existing:  # the page now lives there again
            await session.delete(existing.pop(new))
        graph = {k: v.to for k, v in existing.items() if v.to.startswith('/')}
        # older redirects to the old path now point to the new one (no chains)
        for r in existing.values():
            if r.to == old:
                r.to = new
        if old in existing:
            existing[old].to, existing[old].auto = new, True
        elif not creates_loop(graph, old, new):
            redirect = SiteRedirect(tenant_id=site.tenant_id, site_id=site.id, from_path=old, to=new, status_code=301, auto=True)
            session.add(redirect)
            existing[old] = redirect
    await session.flush()


async def update_page(session: DBAsyncScopedSession, scope: RequestScope, site: Site, page: SitePage, data: PageUpdate) -> SitePage:
    pages = await site_pages(session, site)
    by_id = {p.id: p for p in pages}
    page = by_id[page.id]
    changes: dict[str, Any] = {}
    if data.title is not None:
        title = data.title.strip()
        if not title or len(title) > 200:
            raise ClientException(detail='title must be 1 to 200 characters')
        page.title, changes['title'] = title, title
    structural = False
    if data.slug is not None and data.slug != page.slug:
        if error := page_slug_error(data.slug):
            raise ClientException(detail=error)
        changes['slug'] = {'from': page.slug, 'to': data.slug}
        page.slug, structural = data.slug, True
    if data.parent_id is not msgspec.UNSET:
        new_parent = by_id.get(parse_uuid(data.parent_id, 'parent page', not_found=False)) if data.parent_id else None
        if data.parent_id and new_parent is None:
            raise ClientException(detail='parent page not found')
        cursor = new_parent
        while cursor is not None:
            if cursor.id == page.id:
                raise ClientException(detail='a page cannot move under itself')
            cursor = by_id.get(cursor.parent_id) if cursor.parent_id else None
        if (new_parent.id if new_parent else None) != page.parent_id:
            if _depth(by_id, new_parent) + _subtree_height(pages, page) > MAX_PAGE_DEPTH:
                raise ClientException(detail=f'pages nest at most {MAX_PAGE_DEPTH} levels')
            page.parent_id, structural = (new_parent.id if new_parent else None), True
            changes['parent_id'] = str(page.parent_id) if page.parent_id else None
    if data.position is not None:
        siblings = sorted((p for p in pages if p.parent_id == page.parent_id and p.id != page.id), key=lambda p: p.position)
        siblings.insert(max(0, min(data.position, len(siblings))), page)
        for i, sibling in enumerate(siblings):
            sibling.position = i
        changes['position'] = data.position
    if data.in_menu is not None:
        page.in_menu = data.in_menu
    if data.noindex is not None:
        page.noindex = data.noindex
    if data.seo is not None:
        page.seo = _clean_seo(data.seo)
        changes['seo'] = True
    if structural:
        await _move_paths(session, scope, site, page, pages)
    page.updated_by, page.updated_at = scope.user_id, utcnow()
    site.updated_at = utcnow()
    audit(session, scope, 'page.updated', site_id=site.id, target_type='page', target_id=page.id, changes=changes)
    await session.flush()
    return page


def _subtree_height(pages: list[SitePage], root: SitePage) -> int:
    children = [p for p in pages if p.parent_id == root.id]
    return 1 + max((_subtree_height(pages, c) for c in children), default=0)


def _clean_seo(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, limit in (('title', 120), ('description', 320)):
        value = raw.get(key)
        if value:
            if not isinstance(value, str) or len(value) > limit:
                raise ClientException(detail=f'seo.{key} must be at most {limit} characters')
            out[key] = value.strip()
    canonical = raw.get('canonical')
    if canonical:
        if not isinstance(canonical, str) or not canonical.startswith(('https://', 'http://')):
            raise ClientException(detail='seo.canonical must be an absolute URL')
        out['canonical'] = canonical[:1024]
    og = raw.get('og_image')
    if og:
        if not isinstance(og, str) or not re.match(r'^asset:[0-9a-fA-F-]{36}$', og):
            raise ClientException(detail='seo.og_image must be asset:<id>')
        out['og_image'] = og
    return out


async def delete_page(session: DBAsyncScopedSession, scope: RequestScope, site: Site, page: SitePage) -> int:
    if site.home_page_id == page.id:
        raise ClientException(detail='the home page cannot be deleted: choose another home page first')
    if site.not_found_page_id == page.id:
        raise ClientException(detail='the 404 page cannot be deleted: choose another one first')
    pages = await site_pages(session, site)
    doomed = [page]
    queue = [page.id]
    while queue:
        pid = queue.pop()
        for p in pages:
            if p.parent_id == pid:
                if p.id in (site.home_page_id, site.not_found_page_id):
                    raise ClientException(detail=f'"{p.title}" (home / 404) is below this page: move it first')
                doomed.append(p)
                queue.append(p.id)
    now = utcnow()
    for p in doomed:
        p.deleted_at = now
        await record_usages(session, site.tenant_id, app='sites', ref_type='page', ref_id=p.id, label=None, asset_ids=[])
    site.updated_at = now
    audit(session, scope, 'page.deleted', site_id=site.id, target_type='page', target_id=page.id, title=page.title, count=len(doomed))
    await session.flush()
    return len(doomed)


# --- drafts / revisions / locks -------------------------------------------------------------------


async def save_draft(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    site: Site,
    page: SitePage,
    doc: dict[str, Any],
    *,
    source: str = 'visual',
    base_revision_id: str | None = None,
    title: str | None = None,
    seo: dict[str, Any] | None = None,
    note: str | None = None,
) -> tuple[SitePageRevision, bool]:
    """Validate and store the draft; returns the revision and whether it is a new one."""
    if issues := validate_document(doc):
        raise _invalid(issues)
    holder = _lock_holder(page)
    if holder and holder != scope.user_id:
        names = await user_names(session, [holder])
        raise ConflictException(detail=f'{names.get(holder, "Someone")} is editing this page', extra={'code': 'locked'})
    current = await _draft(session, page)
    if (
        base_revision_id
        and current is not None
        and str(current.id) != base_revision_id
        and current.author_id != scope.user_id
    ):
        raise ConflictException(detail='the page was changed by someone else: reload it', extra={'code': 'stale_draft'})
    if title is not None:
        clean = title.strip()
        if not clean or len(clean) > 200:
            raise ClientException(detail='title must be 1 to 200 characters')
        page.title = clean
    if seo is not None:
        page.seo = _clean_seo(seo)
    now = utcnow()
    reuse = (
        current is not None
        and current.id != page.published_revision_id
        and current.author_id == scope.user_id
        and current.source == source
        and current.created_at > now - REVISION_WINDOW
        and note is None
    )
    if reuse:
        assert current is not None
        current.doc, current.title, current.seo = doc, page.title, page.seo
        revision, created = current, False
    else:
        revision = SitePageRevision(
            id=uuid.uuid7(), tenant_id=site.tenant_id, site_id=site.id, page_id=page.id, doc=doc, source=source,
            title=page.title, seo=page.seo, author_id=scope.user_id, note=(note or None) and note[:500], created_at=now,
        )
        session.add(revision)
        page.draft_revision_id, created = revision.id, True
        audit(session, scope, 'page.draft_saved', site_id=site.id, target_type='page', target_id=page.id, source=source, revision=str(revision.id))
    if holder == scope.user_id:
        page.locked_at = now
    page.updated_by, page.updated_at = scope.user_id, now
    site.updated_at = now
    await _record_usages(session, site, page, doc)
    await session.flush()
    return revision, created


async def list_revisions(session: DBAsyncScopedSession, page: SitePage, limit: int = 50) -> list[RevisionOut]:
    rows = list(
        await session.scalars(
            select(SitePageRevision)
            .where(SitePageRevision.page_id == page.id)
            .order_by(SitePageRevision.created_at.desc())
            .limit(min(limit, 200))
        )
    )
    names = await user_names(session, [r.author_id for r in rows])
    return [
        RevisionOut(
            id=str(r.id), source=r.source, title=r.title, author_id=str(r.author_id) if r.author_id else None,
            author_name=names.get(r.author_id) if r.author_id else None, note=r.note, created_at=r.created_at,
            is_draft=r.id == page.draft_revision_id, is_published=r.id == page.published_revision_id,
        )
        for r in rows
    ]


async def get_revision(session: DBAsyncScopedSession, page: SitePage, revision_id: object) -> RevisionDetailOut:
    rid = parse_uuid(revision_id, 'revision')
    r = await session.scalar(select(SitePageRevision).where(SitePageRevision.id == rid, SitePageRevision.page_id == page.id))
    if r is None:
        raise NotFoundException(detail='revision not found')
    names = await user_names(session, [r.author_id])
    return RevisionDetailOut(
        id=str(r.id), source=r.source, title=r.title, author_id=str(r.author_id) if r.author_id else None,
        author_name=names.get(r.author_id) if r.author_id else None, note=r.note, created_at=r.created_at,
        is_draft=r.id == page.draft_revision_id, is_published=r.id == page.published_revision_id, doc=migrate_document(r.doc),
    )


async def restore_revision(session: DBAsyncScopedSession, scope: RequestScope, site: Site, page: SitePage, revision_id: object) -> SitePageRevision:
    source = await get_revision(session, page, revision_id)
    revision, _ = await save_draft(
        session, scope, site, page, copy.deepcopy(source.doc), source='visual', title=source.title,
        note=f'Restored from {source.created_at:%Y-%m-%d %H:%M}',
    )
    revision.source = 'restore'
    await session.flush()
    return revision


async def lock_page(session: DBAsyncScopedSession, scope: RequestScope, page: SitePage, *, force: bool) -> tuple[bool, UUID | None]:
    """Soft lock (Site-0205): one editor at a time; ``force`` takes over after confirmation."""
    holder = _lock_holder(page)
    if holder and holder != scope.user_id and not force:
        return False, holder
    page.locked_by, page.locked_at = scope.user_id, utcnow()
    await session.flush()
    return True, scope.user_id


async def unlock_page(session: DBAsyncScopedSession, scope: RequestScope, page: SitePage) -> None:
    if page.locked_by == scope.user_id:
        page.locked_by, page.locked_at = None, None
        await session.flush()


# --- menus / redirects ----------------------------------------------------------------------------


async def get_menus(session: DBAsyncScopedSession, site: Site) -> list[MenuOut]:
    menus = {m.key: m for m in await session.scalars(select(SiteMenu).where(SiteMenu.site_id == site.id))}
    return [MenuOut(key=k, items=menus[k].items if k in menus else []) for k in MENU_KEYS]


async def set_menu(session: DBAsyncScopedSession, scope: RequestScope, site: Site, key: str, items: list[dict[str, Any]]) -> MenuOut:
    if key not in MENU_KEYS:
        raise NotFoundException(detail='menu not found')
    clean, errors = normalize_menu(items)
    if errors:
        raise _invalid(errors, 'menu')
    page_ids = {p.id for p in await site_pages(session, site)}

    def check(entries: list[dict[str, Any]]) -> None:
        for e in entries:
            if e.get('page_id') and parse_uuid(e['page_id'], 'page', not_found=False) not in page_ids:
                raise ClientException(detail=f'menu item "{e["label"]}" links to an unknown page')
            check(e.get('children') or [])

    check(clean)
    menu = await session.scalar(select(SiteMenu).where(SiteMenu.site_id == site.id, SiteMenu.key == key))
    if menu is None:
        menu = SiteMenu(tenant_id=site.tenant_id, site_id=site.id, key=key, items=clean)
        session.add(menu)
    else:
        menu.items = clean
    site.updated_at = utcnow()
    audit(session, scope, 'menu.updated', site_id=site.id, target_type='menu', target_id=key)
    await session.flush()
    return MenuOut(key=key, items=clean)


def redirect_out(r: SiteRedirect) -> RedirectOut:
    return RedirectOut(id=str(r.id), from_path=r.from_path, to=r.to, status_code=r.status_code, auto=r.auto, created_at=r.created_at)


async def list_redirects(session: DBAsyncScopedSession, site: Site) -> list[RedirectOut]:
    rows = await session.scalars(select(SiteRedirect).where(SiteRedirect.site_id == site.id).order_by(SiteRedirect.from_path))
    return [redirect_out(r) for r in rows]


async def create_redirect(session: DBAsyncScopedSession, scope: RequestScope, site: Site, from_path: str, to: str, status_code: int) -> SiteRedirect:
    from ._document import is_safe_url

    if not re.match(r'^/[^\s?#]{0,511}$', from_path or ''):
        raise ClientException(detail='from_path must start with / (no query or fragment)')
    if status_code not in (301, 302, 307, 308):
        raise ClientException(detail='status_code must be 301, 302, 307 or 308')
    if not to or not is_safe_url(to) or to.startswith(('mailto:', 'tel:', '#')):
        raise ClientException(detail='to must be a /path or an http(s) URL')
    existing = {r.from_path: r.to for r in await session.scalars(select(SiteRedirect).where(SiteRedirect.site_id == site.id))}
    if from_path in existing:
        raise ConflictException(detail=f'{from_path} already redirects to {existing[from_path]}')
    if to.startswith('/') and creates_loop({k: v for k, v in existing.items() if v.startswith('/')}, from_path, to):
        raise ClientException(detail='this redirect creates a loop')
    redirect = SiteRedirect(tenant_id=site.tenant_id, site_id=site.id, from_path=from_path, to=to, status_code=status_code, auto=False)
    session.add(redirect)
    audit(session, scope, 'redirect.created', site_id=site.id, target_type='redirect', target_id=from_path, to=to)
    await session.flush()
    return redirect


async def delete_redirect(session: DBAsyncScopedSession, scope: RequestScope, site: Site, redirect_id: object) -> None:
    rid = parse_uuid(redirect_id, 'redirect')
    redirect = await session.scalar(select(SiteRedirect).where(SiteRedirect.id == rid, SiteRedirect.site_id == site.id))
    if redirect is None:
        raise NotFoundException(detail='redirect not found')
    await session.delete(redirect)
    audit(session, scope, 'redirect.deleted', site_id=site.id, target_type='redirect', target_id=redirect.from_path)
    await session.flush()


# --- export / import (Site-0007) ------------------------------------------------------------------


async def export_site(session: DBAsyncScopedSession, site: Site) -> dict[str, Any]:
    pages = await site_pages(session, site)
    docs = {r.id: r for r in await session.scalars(select(SitePageRevision).where(SitePageRevision.id.in_([p.draft_revision_id for p in pages if p.draft_revision_id])))}
    menus = {m.key: m.items for m in await get_menus(session, site)}
    redirects = await list_redirects(session, site)
    refs: set[UUID] = set()
    out_pages = []
    for p in pages:
        doc = docs[p.draft_revision_id].doc if p.draft_revision_id in docs else empty_document()
        refs |= asset_ids(doc, (p.seo or {}).get('og_image'))
        out_pages.append({
            'key': str(p.id), 'parent': str(p.parent_id) if p.parent_id else None, 'slug': p.slug, 'path': p.path,
            'title': p.title, 'in_menu': p.in_menu, 'noindex': p.noindex, 'seo': p.seo or {},
            'home': site.home_page_id == p.id, 'not_found': site.not_found_page_id == p.id, 'doc': doc,
        })
    logo = ((site.theme or {}).get('header') or {}).get('logo')
    if logo:
        refs.add(UUID(logo[6:]))
    from db.models.media import MediaAsset

    assets = list(await session.scalars(select(MediaAsset).where(MediaAsset.id.in_(refs)))) if refs else []
    return {
        'format': 'taas-site',
        'version': 1,
        'site': {'name': site.name, 'slug': site.slug, 'description': site.description, 'default_locale': site.default_locale, 'settings': site.settings or {}},
        'theme': site.theme or {},
        'menus': {k: [_menu_keys(i) for i in v] for k, v in menus.items()},
        'pages': out_pages,
        'redirects': [{'from_path': r.from_path, 'to': r.to, 'status_code': r.status_code} for r in redirects],
        'assets': [{'id': str(a.id), 'title': a.title, 'filename': a.filename, 'alt': a.alt, 'mime': a.mime} for a in assets],
    }


def _menu_keys(item: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in item.items() if k != 'children'}
    if item.get('page_id'):
        out['page'] = item['page_id']
    if item.get('children'):
        out['children'] = [_menu_keys(c) for c in item['children']]
    return out


async def import_site(session: DBAsyncScopedSession, scope: RequestScope, name: str, slug: str | None, export: dict[str, Any]) -> Site:
    if export.get('format') != 'taas-site' or export.get('version') != 1:
        raise ClientException(detail='not a site export (format taas-site, version 1)')
    site = await create_site(session, scope, SiteCreate(name=name, slug=slug, template='blank'))
    # replace the blank template content by the export
    for page in await site_pages(session, site):
        page.deleted_at = utcnow()
    for menu in await session.scalars(select(SiteMenu).where(SiteMenu.site_id == site.id)):
        await session.delete(menu)
    await session.flush()
    site.home_page_id = site.not_found_page_id = None
    meta = export.get('site') or {}
    site.description = meta.get('description')
    if isinstance(meta.get('settings'), dict):
        site.settings = _clean_settings(meta['settings'])
    shape = dict(export)
    shape['pages'] = [{**p, 'key': p.get('key'), 'parent': p.get('parent')} for p in export.get('pages') or []]
    await instantiate(session, scope, site, shape, source='import')
    audit(session, scope, 'site.imported', site_id=site.id, target_type='site', target_id=site.id, pages=len(shape['pages']))
    await session.flush()
    return site


async def can_open_app(scope: RequestScope) -> tuple[bool, bool]:
    """``(allowed, can_create)``: an organization-level ``sites.*`` right or a role on a site."""
    can_create = await is_allowed(scope, access.SITE, 'create')
    if can_create or await is_allowed(scope, access.SITE, 'read'):
        return True, can_create
    readable = await access.readable_site_ids(scope)
    return bool(readable), can_create
