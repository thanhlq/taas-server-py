"""``/api/v1/sites`` end to end on the local database (development sign-in unless stated)."""

from __future__ import annotations

import io
import uuid

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


async def _site(client: httpx.AsyncClient, template: str = 'business', **extra) -> dict:
    res = await client.post('/api/v1/sites/', json={'name': f'Acme {uuid.uuid4().hex[:6]}', 'template': template, **extra})
    assert res.status_code == 201, res.text
    return res.json()


def _internal(client: httpx.AsyncClient) -> dict:
    return {'X-Sites-Renderer-Key': RENDERER_KEY}


async def test_create_from_template_and_page_tree(client: httpx.AsyncClient, test_org):
    site = await _site(client)
    assert site['status'] == 'draft' and site['url'] == f'http://{test_org.slug}.sites.test/{site["slug"]}/'
    assert 'sites.page:publish' in site['permissions']
    pages = (await client.get(f'/api/v1/sites/{site["id"]}/pages')).json()
    assert {p['path'] for p in pages} >= {'/home', '/services', '/about', '/contact', '/not-found'}
    home = next(p for p in pages if p['is_home'])
    detail = (await client.get(f'/api/v1/sites/{site["id"]}/pages/{home["id"]}')).json()
    assert detail['doc']['sections'][0]['type'] == 'hero'
    listed = (await client.get('/api/v1/sites/')).json()
    assert site['id'] in [s['id'] for s in listed]
    assert (await client.get('/api/v1/sites/access')).json()['allowed'] is True


async def test_draft_validation_lock_and_revisions(client: httpx.AsyncClient):
    site = await _site(client, 'blank')
    page = (await client.post(f'/api/v1/sites/{site["id"]}/pages', json={'title': 'Team'})).json()
    base = f'/api/v1/sites/{site["id"]}/pages/{page["id"]}'
    bad = await client.put(f'{base}/draft', json={'doc': {'schemaVersion': 1, 'sections': [{'id': 'x', 'type': 'nope'}]}})
    assert bad.status_code == 400 and bad.json()['extra']['issues']
    doc = {'schemaVersion': 1, 'sections': [{'id': 'h', 'type': 'heading', 'props': {'text': 'Our team', 'level': 1}}]}
    first = (await client.put(f'{base}/draft', json={'doc': doc})).json()
    doc['sections'][0]['props']['text'] = 'The team'
    second = (await client.put(f'{base}/draft', json={'doc': doc})).json()
    assert second['new_revision'] is False and second['revision_id'] == first['revision_id']  # autosave window
    third = (await client.put(f'{base}/draft', json={'doc': doc, 'source': 'markdown'})).json()
    assert third['new_revision'] is True
    revisions = (await client.get(f'{base}/revisions')).json()
    assert len(revisions) >= 2 and revisions[0]['is_draft']
    restored = await client.post(f'{base}/revisions/{revisions[-1]["id"]}/restore')
    assert restored.status_code == 200
    lock = (await client.post(f'{base}/lock', json={})).json()
    assert lock['locked'] is True


async def test_publish_slug_redirect_rollback_and_renderer_api(client: httpx.AsyncClient, test_org):
    site = await _site(client, 'business')
    sid = site['id']
    changes = (await client.get(f'/api/v1/sites/{sid}/changes')).json()
    assert len([c for c in changes['changes'] if c['kind'] == 'page_added']) == 5
    first = await client.post(f'/api/v1/sites/{sid}/publish', json={'note': 'Launch'})
    assert first.status_code == 200, first.text
    assert first.json()['number'] == 1 and first.json()['is_live']

    pages = (await client.get(f'/api/v1/sites/{sid}/pages')).json()
    about = next(p for p in pages if p['slug'] == 'about')
    res = await client.patch(f'/api/v1/sites/{sid}/pages/{about["id"]}', json={'slug': 'company'})
    assert res.status_code == 200 and res.json()['path'] == '/company'
    redirects = (await client.get(f'/api/v1/sites/{sid}/redirects')).json()
    assert {(r['from_path'], r['to'], r['auto']) for r in redirects} == {('/about', '/company', True)}
    assert (await client.patch(f'/api/v1/sites/{sid}/pages/{about["id"]}', json={'slug': 'about'})).status_code == 200
    assert (await client.get(f'/api/v1/sites/{sid}/redirects')).json()[0]['from_path'] == '/company'

    second = (await client.post(f'/api/v1/sites/{sid}/publish', json={})).json()
    assert second['number'] == 2

    # renderer view: routing table + immutable snapshot
    routes = (await client.get('/api/v1/sites-internal/routes', headers=_internal(client))).json()
    route = next(r for r in routes['routes'] if r['site_id'] == sid)
    assert route['host'] == f'{test_org.slug}.sites.test' and route['prefix'] == f'/{site["slug"]}'
    assert route['release_id'] == second['id']
    snap = (await client.get(f'/api/v1/sites-internal/releases/{second["id"]}', headers=_internal(client))).json()['snapshot']
    assert {p['path'] for p in snap['pages']} >= {'/', '/services', '/about', '/contact'}
    assert snap['menus']['header'][0]['href'] == '/'
    assert (await client.get('/api/v1/sites-internal/routes')).status_code == 401

    rollback = (await client.post(f'/api/v1/sites/{sid}/releases/{first.json()["id"]}/rollback')).json()
    assert rollback['number'] == 3 and rollback['rollback_of'] == first.json()['id']
    assert (await client.get(f'/api/v1/sites/{sid}')).json()['live_release_id'] == rollback['id']

    link = (await client.post(f'/api/v1/sites/{sid}/preview-links', json={'days': 2})).json()
    token = link['url'].split('/_preview/')[1].split('/')[0]
    preview = await client.get(f'/api/v1/sites-internal/preview/{token}', headers=_internal(client))
    assert preview.status_code == 200 and preview.json()['snapshot']['preview']
    assert (await client.delete(f'/api/v1/sites/{sid}/preview-links')).status_code == 204
    assert (await client.get(f'/api/v1/sites-internal/preview/{token}', headers=_internal(client))).status_code == 404


async def test_accessibility_blocks_publish_until_forced(client: httpx.AsyncClient):
    png = io.BytesIO()
    Image.new('RGB', (64, 64), 'red').save(png, 'PNG')
    asset = (await client.post('/api/v1/media/assets', files={'file': ('x.png', png.getvalue(), 'image/png')})).json()
    site = await _site(client, 'blank')
    home = next(p for p in (await client.get(f'/api/v1/sites/{site["id"]}/pages')).json() if p['is_home'])
    doc = {'schemaVersion': 1, 'sections': [{'id': 'i', 'type': 'image', 'props': {'image': f'asset:{asset["id"]}'}}]}
    assert (await client.put(f'/api/v1/sites/{site["id"]}/pages/{home["id"]}/draft', json={'doc': doc})).status_code == 200
    blocked = await client.post(f'/api/v1/sites/{site["id"]}/publish', json={})
    assert blocked.status_code == 409 and blocked.json()['extra']['code'] == 'accessibility'
    # the page now uses the asset: trashing it needs a confirmation
    assert (await client.delete(f'/api/v1/media/assets/{asset["id"]}')).status_code == 409
    usages = (await client.get(f'/api/v1/media/assets/{asset["id"]}/usages')).json()
    assert usages[0]['app'] == 'sites'
    forced = await client.post(f'/api/v1/sites/{site["id"]}/publish', json={'ignore_accessibility': True})
    assert forced.status_code == 200
    snap = (await client.get(f'/api/v1/sites-internal/releases/{forced.json()["id"]}', headers=_internal(client))).json()['snapshot']
    assert asset['id'] in snap['assets']
    raw = await client.get(f'/api/v1/sites-internal/assets/{snap["site"]["tenant_id"]}/{asset["id"]}/w64.webp', headers=_internal(client))
    assert raw.status_code == 200 and raw.headers['content-type'] == 'image/webp'


async def test_publish_copies_media_to_the_cdn_and_unpublish_removes_them(client: httpx.AsyncClient):
    """Storage spec §3.1: publish = content-hashed public copies, unpublish = delete the site prefix, rollback re-copies."""
    from blob_service import AdapterPublicStore
    from ews.sites._cdn import public_store
    from foundation.blob import BlobListOptions

    store = public_store()
    assert isinstance(store, AdapterPublicStore)

    async def public_keys(prefix: str) -> list[str]:
        return [i.key for i in (await store.adapter.list(store.bucket, BlobListOptions(prefix=prefix))).items]

    png = io.BytesIO()
    Image.new('RGB', (64, 48), 'blue').save(png, 'PNG')
    asset = (await client.post('/api/v1/media/assets', files={'file': ('cdn.png', png.getvalue(), 'image/png')})).json()
    site = await _site(client, 'blank')
    sid = site['id']
    home = next(p for p in (await client.get(f'/api/v1/sites/{sid}/pages')).json() if p['is_home'])
    doc = {'schemaVersion': 1, 'sections': [{'id': 'i', 'type': 'image', 'props': {'image': f'asset:{asset["id"]}', 'alt': 'Blue'}}]}
    assert (await client.put(f'/api/v1/sites/{sid}/pages/{home["id"]}/draft', json={'doc': doc})).status_code == 200
    first = (await client.post(f'/api/v1/sites/{sid}/publish', json={})).json()
    snap = (await client.get(f'/api/v1/sites-internal/releases/{first["id"]}', headers=_internal(client))).json()['snapshot']
    public = snap['assets'][asset['id']]['public']
    tenant = snap['site']['tenant_id']
    prefix = f'{tenant}/site/{sid}/'
    assert snap['cdn_origin'] == 'https://cdn.test'
    assert public['original'].startswith(f'https://cdn.test/{prefix}') and public['original'].endswith('.png')
    assert set(public['variants']) == {'w64.webp', 'w64.avif'} or set(public['variants']) == {'w64.webp'}
    keys = await public_keys(prefix)
    assert len(keys) == 1 + len(public['variants'])
    info = await store.adapter.head(store.bucket, keys[0])
    assert info is not None and info.content_type in ('image/png', 'image/webp', 'image/avif')

    # publishing again does not duplicate (content-hashed keys)
    assert (await client.put(f'/api/v1/sites/{sid}/pages/{home["id"]}/draft', json={'doc': doc, 'title': 'Home 2'})).status_code == 200
    second = (await client.post(f'/api/v1/sites/{sid}/publish', json={})).json()
    assert sorted(await public_keys(prefix)) == sorted(keys)

    # unpublish removes the public copies; rollback copies them again
    assert (await client.post(f'/api/v1/sites/{sid}/unpublish')).status_code in (200, 204)
    assert await public_keys(prefix) == []
    rolled = await client.post(f'/api/v1/sites/{sid}/releases/{second["id"]}/rollback')
    assert rolled.status_code == 200
    assert sorted(await public_keys(prefix)) == sorted(keys)

    # deleting the site removes them for good
    assert (await client.delete(f'/api/v1/sites/{sid}')).status_code in (200, 204)
    assert await public_keys(prefix) == []


async def test_contact_form_submission(client: httpx.AsyncClient):
    site = await _site(client, 'business')
    sid = site['id']
    release = (await client.post(f'/api/v1/sites/{sid}/publish', json={})).json()
    snap = (await client.get(f'/api/v1/sites-internal/releases/{release["id"]}', headers=_internal(client))).json()['snapshot']
    contact = next(p for p in snap['pages'] if p['path'] == '/contact')
    form = contact['doc']['sections'][0]['children'][0]['children'][1]['children'][0]
    assert form['type'] == 'form'
    url = f'/api/v1/sites-internal/forms/{sid}/{form["id"]}'
    bad = await client.post(url, json={'data': {'name': 'Ann'}, 'page_id': contact['id']}, headers=_internal(client))
    assert bad.status_code == 400
    ok = await client.post(
        url, json={'data': {'name': 'Ann', 'email': 'ann@example.com', 'message': 'Hello', 'extra': 'x'}, 'ip_hash': 'h1'},
        headers=_internal(client),
    )
    assert ok.status_code == 200 and ok.json()['ok']
    subs = (await client.get(f'/api/v1/sites/{sid}/submissions')).json()
    assert subs['total'] == 1 and subs['items'][0]['data'] == {'name': 'Ann', 'email': 'ann@example.com', 'message': 'Hello'}
    csv = await client.get(f'/api/v1/sites/{sid}/submissions/export')
    assert csv.status_code == 200 and 'ann@example.com' in csv.text


async def test_theme_menus_export_import(client: httpx.AsyncClient):
    site = await _site(client, 'cafe')
    sid = site['id']
    res = await client.put(f'/api/v1/sites/{sid}/theme', json={'theme': {'colors': {'text': '#bbbbbb', 'background': '#ffffff'}}})
    assert res.status_code == 200 and any(i['code'] == 'contrast' for i in res.json()['issues'])
    assert (await client.put(f'/api/v1/sites/{sid}/theme', json={'theme': {'fonts': {'body': 'Comic'}}})).status_code == 400
    menus = (await client.get(f'/api/v1/sites/{sid}/menus')).json()
    header = next(m for m in menus if m['key'] == 'header')
    assert header['items'][0]['page_id']
    bad = await client.put(f'/api/v1/sites/{sid}/menus/header', json={'items': [{'label': 'X', 'page_id': str(uuid.uuid4())}]})
    assert bad.status_code == 400
    exported = (await client.get(f'/api/v1/sites/{sid}/export')).json()
    assert exported['format'] == 'taas-site' and len(exported['pages']) == 4
    imported = await client.post('/api/v1/sites/import', json={'name': 'Copy of café', 'export': exported})
    assert imported.status_code == 201, imported.text
    pages = (await client.get(f'/api/v1/sites/{imported.json()["id"]}/pages')).json()
    assert sorted(p['path'] for p in pages) == sorted(p['path'] for p in exported['pages'])


async def test_ai_assist_with_the_fake_provider(client: httpx.AsyncClient, monkeypatch):
    from ews.ai import ai_settings
    from ews.ai._gateway import FakeGateway

    monkeypatch.setenv('AI_GATEWAY_PROVIDER', 'fake')
    ai_settings.cache_clear()
    from ews.ai import use_ai_gateway

    use_ai_gateway(FakeGateway())
    try:
        site = await _site(client, 'blank')
        sid = site['id']
        text = (await client.post(f'/api/v1/sites/{sid}/ai/text', json={'action': 'shorten', 'text': 'One. Two. Three.'})).json()
        assert text['text'] == 'One.'
        section = await client.post(f'/api/v1/sites/{sid}/ai/section', json={'prompt': 'Three reasons to choose us'})
        assert section.status_code == 200 and section.json()['blocks'][0]['type'] == 'features'
        home = next(p for p in (await client.get(f'/api/v1/sites/{sid}/pages')).json() if p['is_home'])
        seo = (await client.post(f'/api/v1/sites/{sid}/ai/seo', json={'page_id': home['id']})).json()
        assert seo['title'] and seo['description']
        assert (await client.post(f'/api/v1/sites/{sid}/ai/feedback', json={'request_id': text['request_id'], 'accepted': True})).status_code == 204
        usage = (await client.get(f'/api/v1/sites/{sid}/ai/usage')).json()
        assert usage['enabled'] and usage['used'] > 0
        audit = (await client.get(f'/api/v1/sites/{sid}/audit')).json()
        assert {'ai.shorten', 'ai.section', 'ai.accepted'} <= {a['action'] for a in audit}
    finally:
        use_ai_gateway(None)
        ai_settings.cache_clear()


async def test_permissions_in_iam_mode(app, test_org, sql):
    """A member without site rights gets 403 on create and an empty, not-allowed app; a site role grants
    exactly that site; org admins see everything."""
    from ews.authz import grant, revoke_domain
    from ews.security import EwsAuthSettings, SessionVerifierT, VerifiedSession, configure_security

    class Verifier(SessionVerifierT):
        async def verify(self, headers):
            return VerifiedSession(sub=headers['authorization'].split()[1])

    sub = (await _sub(test_org))
    await sql(
        "insert into taas_organization_members (id, user_id, organization_id, tenant_id, role, is_owner, created_at, updated_at, joined_via) "
        "values (:id, :u, :o, :t, 'org_member', false, now(), now(), 'admin') on conflict do nothing",
        {'id': uuid.uuid4(), 'u': test_org.user_id, 'o': test_org.organization_id, 't': test_org.tenant_id},
    )
    await grant(test_org.user_id, 'org_member', f'org:{test_org.organization_id}')  # the IAM grants it with the membership
    configure_security(settings=EwsAuthSettings(mode='iam'), verifier=Verifier())
    headers = {'Authorization': f'Bearer {sub}', 'X-Organization-Id': str(test_org.organization_id)}
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver', headers=headers) as c:
            access = (await c.get('/api/v1/sites/access')).json()
            assert access == {**access, 'allowed': False, 'can_create': False}
            assert (await c.post('/api/v1/sites/', json={'name': 'Nope'})).status_code == 403
            # foreign organization → 404 (not a member)
            other = {'X-Organization-Id': str(uuid.uuid4())}
            assert (await c.get('/api/v1/sites/', headers=other)).status_code == 404

            await grant(test_org.user_id, 'org_admin', f'org:{test_org.organization_id}')
            created = await c.post('/api/v1/sites/', json={'name': 'Admin site', 'template': 'blank'})
            assert created.status_code == 201, created.text
            site_id = created.json()['id']
            await revoke_domain(f'org:{test_org.organization_id}', user_id=test_org.user_id)
            await grant(test_org.user_id, 'org_member', f'org:{test_org.organization_id}')

            # still site_admin of the created site (creator grant), but cannot create new sites
            access = (await c.get('/api/v1/sites/access')).json()
            assert access['allowed'] is True and access['can_create'] is False
            assert [s['id'] for s in (await c.get('/api/v1/sites/')).json()] == [site_id]
            await revoke_domain(f'site:{site_id}', user_id=test_org.user_id)
            await grant(test_org.user_id, 'site_author', f'site:{site_id}')
            site = (await c.get(f'/api/v1/sites/{site_id}')).json()
            assert 'sites.page:update' in site['permissions'] and 'sites.page:publish' not in site['permissions']
            assert (await c.post(f'/api/v1/sites/{site_id}/publish', json={})).status_code == 403
            assert (await c.put(f'/api/v1/sites/{site_id}/theme', json={'theme': {}})).status_code == 403
            # media: org members browse and upload, but do not delete
            assert (await c.get('/api/v1/media/assets')).status_code == 200
            assert (await c.delete(f'/api/v1/media/assets/{uuid.uuid4()}')).status_code == 403
    finally:
        configure_security(settings=EwsAuthSettings(mode='dev', dev_organization_id=str(test_org.organization_id)))


async def _sub(test_org) -> str:
    from foundation.db.advanced_db_manager import MainDatabase
    from sqlalchemy import text

    async with MainDatabase.get_instance().get_engine().connect() as conn:
        return (await conn.execute(text('select directory_id from taas_user_account where id = :id'), {'id': test_org.user_id})).scalar_one()
