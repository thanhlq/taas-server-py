"""Blog addresses and public reading on the local database (taas-specs/blog/blog-publishing-spec.md, B3 core):
slugs (Blog-0106…0110), releases + the renderer API (``/api/v1/sites-internal``), media on the public CDN.

The test app uses an in-memory public store (``https://cdn.test``, conftest) and ``SITES_DOMAIN=sites.test``.
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from PIL import Image

RENDERER_KEY = 'test-renderer-key'


@pytest.fixture(autouse=True)
def _renderer_key(monkeypatch):
    from ews.sites._settings import sites_settings

    monkeypatch.setenv('SITES_RENDERER_KEY', RENDERER_KEY)
    monkeypatch.setenv('SITES_DOMAIN', 'sites.test')
    monkeypatch.setenv('SITES_PUBLIC_PORT', '')
    sites_settings.cache_clear()
    yield
    sites_settings.cache_clear()


KEY = {'X-Sites-Renderer-Key': RENDERER_KEY}


def _doc(*blocks: dict) -> dict:
    return {'schemaVersion': 1, 'sections': list(blocks)}


def _text(text: str, bid: str = 'r1') -> dict:
    return {
        'id': bid,
        'type': 'richText',
        'content': {
            'type': 'doc',
            'content': [
                {'type': 'paragraph', 'content': [{'type': 'text', 'text': text}]}
            ],
        },
    }


def _png(color: str) -> bytes:
    out = io.BytesIO()
    Image.new('RGB', (64, 48), color).save(out, 'PNG')
    return out.getvalue()


async def _blog(client: httpx.AsyncClient, **extra) -> dict:
    res = await client.post(
        '/api/v1/blog/blogs',
        json={'name': 'Docs', 'slug': f'docs-{uuid.uuid4().hex[:6]}', **extra},
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _post(client: httpx.AsyncClient, blog_id: str, **extra) -> dict:
    res = await client.post(f'/api/v1/blog/blogs/{blog_id}/posts', json=extra)
    assert res.status_code == 201, res.text
    return res.json()


async def _patch(client: httpx.AsyncClient, pid: str, **data) -> httpx.Response:
    return await client.patch(f'/api/v1/blog/posts/{pid}', json=data)


async def _route(client: httpx.AsyncClient, blog_id: str) -> dict | None:
    res = await client.get('/api/v1/sites-internal/routes', headers=KEY)
    assert res.status_code == 200, res.text
    return next((r for r in res.json()['routes'] if r.get('blog_id') == blog_id), None)


async def _snapshot(client: httpx.AsyncClient, blog_id: str) -> dict:
    route = await _route(client, blog_id)
    assert route is not None
    res = await client.get(
        f'/api/v1/sites-internal/blog-releases/{route["release_id"]}', headers=KEY
    )
    assert res.status_code == 200, res.text
    assert res.json()['release_id'] == route['release_id']
    return res.json()['snapshot']


# --- slugs (Blog-0106…0109) ---------------------------------------------------------------------------


async def test_blog_0106_0107_slug_follows_the_title_until_published(
    client: httpx.AsyncClient,
):
    blog = await _blog(client)
    bid = blog['id']
    post = await _post(client, bid, title='Getting started with Đà Nẵng')
    pid = post['id']
    assert post['slug'] == 'getting-started-with-da-nang' and post['slug_auto'] is True
    assert 'former_slugs' not in post  # omit_defaults: []

    # draft autosave and metadata both move the address while it is automatic
    res = await client.put(
        f'/api/v1/blog/posts/{pid}/draft',
        json={'title': 'Straße über Größe', 'doc': _doc(_text('Hallo'))},
    )
    assert res.status_code == 200, res.text
    # the autosave answer carries the new address, so the editor shows it exactly (with any -2 suffix)
    saved = res.json()
    assert saved['slug'] == 'strasse-uber-grosse' and saved['slug_auto'] is True
    assert saved['public_url'].endswith('/strasse-uber-grosse')
    detail = (await client.get(f'/api/v1/blog/posts/{pid}')).json()
    assert detail['slug'] == 'strasse-uber-grosse'
    assert (await _patch(client, pid, title='Zażółć gęślą jaźń')).json()[
        'slug'
    ] == 'zazolc-gesla-jazn'
    # no Latin letters → "post"; a reserved word or a used slug gets a suffix
    assert (await _patch(client, pid, title='日本語のタイトル')).json()[
        'slug'
    ] == 'post'
    assert (await _patch(client, pid, title='Page')).json()['slug'] == 'page-2'
    other = await _post(client, bid, title='Taken')
    assert (await _patch(client, pid, title='Taken')).json()['slug'] == 'taken-2'
    # a revision restored with another title moves it too
    revisions = (await client.get(f'/api/v1/blog/posts/{pid}/revisions')).json()
    await client.put(
        f'/api/v1/blog/posts/{pid}/draft',
        json={'title': 'Renamed', 'doc': _doc(_text('x')), 'note': 'v2'},
    )
    assert (await client.get(f'/api/v1/blog/posts/{pid}')).json()['slug'] == 'renamed'
    restored = await client.post(
        f'/api/v1/blog/posts/{pid}/revisions/{revisions[-1]["id"]}/restore'
    )
    assert restored.status_code == 200
    assert (await client.get(f'/api/v1/blog/posts/{pid}')).json()['slug'] == 'taken-2'

    # a hand-made slug stops it; the same value again changes nothing
    manual = (await _patch(client, pid, slug='my-address')).json()
    assert manual['slug'] == 'my-address' and 'slug_auto' not in manual
    assert (await _patch(client, pid, title='Another title')).json()[
        'slug'
    ] == 'my-address'
    # "" regenerates from the current title and turns it back on (never published)
    regenerated = (await _patch(client, pid, slug='')).json()
    assert regenerated['slug'] == 'another-title' and regenerated['slug_auto'] is True

    # validation: reserved (Blog-0109) / invalid → 400, used → 409
    for reserved in ('page', 'category', 'tag', 'author', 'feed.xml', 'Bad Slug'):
        res = await _patch(client, pid, slug=reserved)
        assert res.status_code == 400, reserved
    res = await _patch(client, pid, slug=other['slug'])
    assert res.status_code == 409 and res.json()['extra']['code'] == 'slug_taken'
    created = await client.post(
        f'/api/v1/blog/blogs/{bid}/posts', json={'title': 'X', 'slug': 'author'}
    )
    assert created.status_code == 400
    explicit = await _post(client, bid, title='Explicit', slug='chosen-slug')
    assert explicit['slug'] == 'chosen-slug' and 'slug_auto' not in explicit
    # categories / tags may use words reserved for posts
    tag = await client.post(f'/api/v1/blog/blogs/{bid}/tags', json={'name': 'Page'})
    assert tag.status_code == 201 and tag.json()['slug'] == 'page'


async def test_blog_0108_0110_frozen_after_publish_former_slugs_public_url(
    client: httpx.AsyncClient, test_org
):
    blog = await _blog(client)
    bid = blog['id']
    base = f'http://{test_org.slug}.sites.test/{blog["slug"]}/'
    assert blog['public_url'] == base
    listed = (await client.get('/api/v1/blog/blogs')).json()
    assert next(b for b in listed if b['id'] == bid)['public_url'] == base

    post = await _post(client, bid, title='Launch day', doc=_doc(_text('We launched')))
    pid = post['id']
    assert post['public_url'] == f'{base}launch-day' and 'live' not in post

    published = (await client.post(f'/api/v1/blog/posts/{pid}/publish')).json()
    assert published['live'] is True and 'slug_auto' not in published
    # frozen: the title no longer moves the address (draft change only)
    retitled = (await _patch(client, pid, title='Launch day, revisited')).json()
    assert retitled['slug'] == 'launch-day' and retitled['has_changes'] is True

    # a hand-made change keeps the old address (301) and is public at once
    moved = (await _patch(client, pid, slug='launch')).json()
    assert moved['slug'] == 'launch' and moved['former_slugs'] == ['launch-day']
    assert moved['public_url'] == f'{base}launch'
    snap = await _snapshot(client, bid)
    (entry,) = snap['posts']
    assert entry['slug'] == 'launch' and entry['former_slugs'] == ['launch-day']
    assert entry['title'] == 'Launch day'  # the live revision, not the pending draft
    # a slug-only change does not create pending changes on a post without any
    post2 = await _post(client, bid, title='Second', doc=_doc(_text('Two')))
    await client.post(f'/api/v1/blog/posts/{post2["id"]}/publish')
    only_slug = (await _patch(client, post2['id'], slug='second-post')).json()
    assert not only_slug.get('has_changes') and only_slug['former_slugs'] == ['second']
    # back to a former address: it is current again; "" = from the title, still kept as former
    back = (await _patch(client, pid, slug='launch-day')).json()
    assert back['former_slugs'] == ['launch']
    regenerated = (await _patch(client, pid, slug='')).json()
    assert regenerated['slug'] == 'launch-day-revisited'
    assert regenerated['former_slugs'] == ['launch', 'launch-day']
    assert 'slug_auto' not in regenerated  # published once: never automatic again

    # live = published and the blog active
    await client.patch(f'/api/v1/blog/blogs/{bid}', json={'status': 'archived'})
    assert 'live' not in (await client.get(f'/api/v1/blog/posts/{pid}')).json()
    await client.patch(f'/api/v1/blog/blogs/{bid}', json={'status': 'active'})
    assert (await client.get(f'/api/v1/blog/posts/{pid}')).json()['live'] is True
    await client.post(f'/api/v1/blog/posts/{pid}/unpublish')
    assert 'live' not in (await client.get(f'/api/v1/blog/posts/{pid}')).json()


# --- releases + renderer API (blog-publishing-spec §3 / §5) ----------------------------------------------


async def test_releases_follow_every_public_change(
    client: httpx.AsyncClient, test_org, sql
):
    from ews.blog import publish_due

    blog = await _blog(client, description='Product docs', locale='fr')
    bid = blog['id']
    # a new blog is served at once (empty home)
    route = await _route(client, bid)
    assert route == {
        'host': f'{test_org.slug}.sites.test',
        'prefix': f'/{blog["slug"]}',
        'blog_id': bid,
        'tenant_id': str(test_org.tenant_id),
        'release_id': route['release_id'],
        'kind': 'blog',
    }
    snap = await _snapshot(client, bid)
    assert snap['schema'] == 1 and snap['kind'] == 'blog' and snap['version'] == 1
    assert snap['release_id'] == route['release_id'] and snap['generated_at']
    assert snap['blog'] == {
        'id': bid,
        'slug': blog['slug'],
        'name': 'Docs',
        'description': 'Product docs',
        'locale': 'fr',
        'settings': {
            'posts_per_page': 10,
            'feed_full_text': False,
            'feed_enabled': True,
        },
    }
    assert snap['organization'] == {'slug': test_org.slug, 'name': 'EWS test'}
    assert snap['base_url'] == f'http://{test_org.slug}.sites.test/{blog["slug"]}/'
    assert snap['posts'] == [] and snap['gone'] == [] and snap['assets'] == {}
    assert snap['cdn_origin'] is None

    # drafts never leave the API; a change that is not public builds no release
    category = (
        await client.post(
            f'/api/v1/blog/blogs/{bid}/categories', json={'name': 'Guides'}
        )
    ).json()
    tag = (
        await client.post(f'/api/v1/blog/blogs/{bid}/tags', json={'name': 'API'})
    ).json()
    first = await _post(
        client,
        bid,
        title='First',
        doc=_doc(_text('one two three')),
        category_id=category['id'],
        tag_ids=[tag['id']],
    )
    await client.patch(f'/api/v1/blog/blogs/{bid}', json={'name': 'Docs'})
    assert (await _snapshot(client, bid))['version'] == 1

    # publish → in the release with the metadata of the live revision
    await client.post(f'/api/v1/blog/posts/{first["id"]}/publish')
    snap = await _snapshot(client, bid)
    assert snap['version'] == 2
    (entry,) = snap['posts']
    assert entry['slug'] == 'first' and entry['revision_id']
    assert entry['category_id'] == category['id'] and entry['tag_ids'] == [tag['id']]
    assert entry['reading_minutes'] == 1 and entry['published_at']
    assert [c['slug'] for c in snap['categories']] == ['guides']
    assert snap['tags'] == [{'id': tag['id'], 'slug': 'api', 'name': 'API'}]
    (author,) = snap['authors']
    assert entry['author_ids'] == [author['id']] and author['avatar'] is None
    assert set(author) == {'id', 'slug', 'name', 'bio', 'avatar', 'links'}

    # the body: published revisions only
    body = await client.get(
        f'/api/v1/sites-internal/blog-posts/{entry["revision_id"]}', headers=KEY
    )
    assert body.status_code == 200, body.text
    assert body.json() == {
        'revision_id': entry['revision_id'],
        'doc': _doc(_text('one two three')),
        'assets': {},
        'cdn_origin': None,
    }
    await client.put(
        f'/api/v1/blog/posts/{first["id"]}/draft', json={'doc': _doc(_text('draft'))}
    )
    draft_id = (await client.get(f'/api/v1/blog/posts/{first["id"]}')).json()[
        'draft_revision_id'
    ]
    for rid in (draft_id, str(uuid.uuid4()), 'nope'):
        res = await client.get(f'/api/v1/sites-internal/blog-posts/{rid}', headers=KEY)
        assert res.status_code == 404, rid

    # settings / name / taxonomy changes of the public output → new releases
    await client.patch(
        f'/api/v1/blog/blogs/{bid}', json={'settings': {'posts_per_page': 5}}
    )
    snap = await _snapshot(client, bid)
    assert snap['version'] == 3 and snap['blog']['settings']['posts_per_page'] == 5
    await client.patch(
        f'/api/v1/blog/blogs/{bid}/tags/{tag["id"]}', json={'name': 'REST API'}
    )
    assert (await _snapshot(client, bid))['tags'][0]['name'] == 'REST API'

    # scheduled posts join the release when the scheduler publishes them
    later = await _post(client, bid, title='Later', doc=_doc(_text('later')))
    await client.post(
        f'/api/v1/blog/posts/{later["id"]}/schedule',
        json={'scheduled_at': '2099-01-01T09:00:00', 'timezone': 'UTC'},
    )
    await sql(
        'update taas_blog_posts set scheduled_at = :at where id = :id',
        {'at': datetime.now(UTC) - timedelta(minutes=1), 'id': later['id']},
    )
    assert await publish_due(tenant_id=test_org.tenant_id) == [uuid.UUID(later['id'])]
    snap = await _snapshot(client, bid)
    # newest first by publication: "later" went live at its scheduled time, a minute ago
    assert [p['slug'] for p in snap['posts']] == ['first', 'later']

    # unpublish → out (404 on the public site, not gone); delete → gone with its former slugs (410)
    await client.post(f'/api/v1/blog/posts/{later["id"]}/unpublish')
    snap = await _snapshot(client, bid)
    assert [p['slug'] for p in snap['posts']] == ['first'] and snap['gone'] == []
    await _patch(client, first['id'], slug='first-post')
    assert (await client.delete(f'/api/v1/blog/posts/{first["id"]}')).status_code == 204
    snap = await _snapshot(client, bid)
    assert snap['posts'] == [] and snap['gone'] == ['first', 'first-post']
    assert snap['categories'] == [] and snap['tags'] == [] and snap['authors'] == []
    # the unpublished one is not gone; its body is no longer served once deleted
    assert (
        await client.get(
            f'/api/v1/sites-internal/blog-posts/{entry["revision_id"]}', headers=KEY
        )
    ).status_code == 404
    # a new post may take a gone address again
    again = await _post(client, bid, title='First', doc=_doc(_text('again')))
    await client.post(f'/api/v1/blog/posts/{again["id"]}/publish')
    snap = await _snapshot(client, bid)
    assert [p['slug'] for p in snap['posts']] == ['first'] and snap['gone'] == [
        'first-post'
    ]

    # only the last 20 releases are kept
    for n in range(21):
        await client.patch(
            f'/api/v1/blog/blogs/{bid}', json={'description': f'Description {n}'}
        )
    live = await _route(client, bid)
    versions = await _versions(bid)
    assert (
        len(versions) == 20
        and max(versions) == (await _snapshot(client, bid))['version']
    )
    assert live is not None


async def _versions(blog_id: str) -> list[int]:
    """Release versions of a blog (direct SQL: the API exposes only the live one)."""
    from foundation.db.advanced_db_manager import MainDatabase
    from sqlalchemy import text

    async with MainDatabase.get_instance().get_engine().connect() as conn:
        rows = await conn.execute(
            text('select version from taas_blog_releases where blog_id = :b'),
            {'b': uuid.UUID(blog_id)},
        )
        return sorted(r[0] for r in rows)


async def test_renderer_api_needs_the_key_and_routes_keep_the_sites(
    client: httpx.AsyncClient,
):
    blog = await _blog(client)
    route = await _route(client, blog['id'])
    assert route is not None
    paths = (
        '/api/v1/sites-internal/routes',
        f'/api/v1/sites-internal/blog-releases/{route["release_id"]}',
        f'/api/v1/sites-internal/blog-posts/{uuid.uuid4()}',
    )
    for path in paths:
        assert (await client.get(path)).status_code == 401, path
        wrong = await client.get(path, headers={'X-Sites-Renderer-Key': 'nope'})
        assert wrong.status_code == 401, path
    unknown = await client.get(
        f'/api/v1/sites-internal/blog-releases/{uuid.uuid4()}', headers=KEY
    )
    assert unknown.status_code == 404

    # sites keep their routes next to the blogs (one digest for both)
    site = await client.post(
        '/api/v1/sites/', json={'name': 'Shop', 'slug': f'shop-{uuid.uuid4().hex[:6]}'}
    )
    sid = site.json()['id']
    assert (
        await client.post(f'/api/v1/sites/{sid}/publish', json={})
    ).status_code == 200
    table = (await client.get('/api/v1/sites-internal/routes', headers=KEY)).json()
    site_route = next(r for r in table['routes'] if r.get('site_id') == sid)
    assert 'blog_id' not in site_route and site_route.get('kind', 'site') == 'site'
    version = table['version']
    await client.patch(
        f'/api/v1/blog/blogs/{blog["id"]}', json={'slug': f'{blog["slug"]}-x'}
    )
    table = (await client.get('/api/v1/sites-internal/routes', headers=KEY)).json()
    assert table['version'] != version
    moved = next(r for r in table['routes'] if r.get('blog_id') == blog['id'])
    assert moved['prefix'] == f'/{blog["slug"]}-x'
    snap = await _snapshot(client, blog['id'])
    assert snap['blog']['slug'] == f'{blog["slug"]}-x' and snap['base_url'].endswith(
        '-x/'
    )

    # archived / deleted blogs leave the routing table
    await client.patch(f'/api/v1/blog/blogs/{blog["id"]}', json={'status': 'archived'})
    assert await _route(client, blog['id']) is None
    await client.patch(f'/api/v1/blog/blogs/{blog["id"]}', json={'status': 'active'})
    assert await _route(client, blog['id']) is not None
    await client.delete(f'/api/v1/blog/blogs/{blog["id"]}')
    assert await _route(client, blog['id']) is None
    gone = await client.get(
        f'/api/v1/sites-internal/blog-releases/{route["release_id"]}', headers=KEY
    )
    assert gone.status_code == 404


# --- media on the public CDN (storage §3) -----------------------------------------------------------------


async def test_publish_copies_media_to_the_blog_scope(client: httpx.AsyncClient):
    from blob_service import AdapterPublicStore
    from ews.media import public_store
    from foundation.blob import BlobListOptions

    store = public_store()
    assert isinstance(store, AdapterPublicStore)

    async def public_keys(prefix: str) -> list[str]:
        listed = await store.adapter.list(store.bucket, BlobListOptions(prefix=prefix))
        return sorted(i.key for i in listed.items)

    async def upload(name: str, color: str) -> str:
        res = await client.post(
            '/api/v1/media/assets', files={'file': (name, _png(color), 'image/png')}
        )
        assert res.status_code == 201, res.text
        return res.json()['id']

    body_img, cover, avatar = (
        await upload('body.png', 'navy'),
        await upload('cover.png', 'olive'),
        await upload('avatar.png', 'maroon'),
    )
    blog = await _blog(client)
    bid = blog['id']
    author = (
        await client.post(
            f'/api/v1/blog/blogs/{bid}/authors',
            json={'display_name': 'Ann', 'avatar_asset_id': avatar, 'links': []},
        )
    ).json()
    image = {
        'id': 'i1',
        'type': 'image',
        'props': {'image': f'asset:{body_img}', 'alt': 'Navy'},
    }
    post = await _post(
        client, bid, title='Pictures', doc=_doc(image), author_ids=[author['id']]
    )
    await _patch(client, post['id'], cover_asset_id=cover, cover_alt='Olive')
    await client.post(f'/api/v1/blog/posts/{post["id"]}/publish')

    snap = await _snapshot(client, bid)
    tenant = (await _route(client, bid))['tenant_id']
    prefix = f'{tenant}/blog/{bid}/'
    assert snap['cdn_origin'] == 'https://cdn.test'
    # the release: cover + avatar (+ social images)
    assert set(snap['assets']) == {cover, avatar}
    for aid in (cover, avatar):
        public = snap['assets'][aid]['public']
        assert public['original'].startswith(f'https://cdn.test/{prefix}')
        assert (
            snap['assets'][aid]['kind'] == 'image' and snap['assets'][aid]['variants']
        )
    (entry,) = snap['posts']
    assert entry['cover'] == {'asset_id': cover, 'alt': 'Olive'}
    assert snap['authors'][0]['avatar'] == f'asset:{avatar}'
    # the body: its media + the cover
    body = (
        await client.get(
            f'/api/v1/sites-internal/blog-posts/{entry["revision_id"]}', headers=KEY
        )
    ).json()
    assert body['cdn_origin'] == 'https://cdn.test' and set(body['assets']) == {
        body_img,
        cover,
    }
    assert body['assets'][body_img]['public']['original'].startswith(
        f'https://cdn.test/{prefix}'
    )
    keys = await public_keys(prefix)
    assert keys and all(k.startswith(prefix) for k in keys)

    # archive removes the public copies, restore copies them again, delete removes them for good
    await client.patch(f'/api/v1/blog/blogs/{bid}', json={'status': 'archived'})
    assert await public_keys(prefix) == []
    await client.patch(f'/api/v1/blog/blogs/{bid}', json={'status': 'active'})
    assert await public_keys(prefix) == keys
    assert (await client.delete(f'/api/v1/blog/blogs/{bid}')).status_code == 204
    assert await public_keys(prefix) == []
