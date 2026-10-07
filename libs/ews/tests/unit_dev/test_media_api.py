"""``/api/v1/media`` end to end on the local database (memory blob storage, development sign-in)."""

from __future__ import annotations

import io

import httpx
from PIL import Image


def _png(width: int = 800, height: int = 600, color: str = 'royalblue') -> bytes:
    out = io.BytesIO()
    Image.new('RGB', (width, height), color).save(out, 'PNG')
    return out.getvalue()


async def _upload(client: httpx.AsyncClient, name: str = 'Hero banner.png', data: bytes | None = None, **fields: str):
    return await client.post('/api/v1/media/assets', files={'file': (name, data or _png(), 'image/png')}, data=fields)


async def test_upload_list_and_deliver_an_image(client: httpx.AsyncClient):
    res = await _upload(client, alt='Blue hero')
    assert res.status_code == 201, res.text
    asset = res.json()
    assert asset['kind'] == 'image' and asset['mime'] == 'image/png'
    assert (asset['width'], asset['height']) == (800, 600)
    assert asset['title'] == 'Hero banner'
    assert asset['alt'] == 'Blue hero'
    assert {'w320.webp', 'w640.webp', 'w800.webp'} <= set(asset['variants'])

    page = (await client.get('/api/v1/media/assets', params={'tab': 'images', 'q': 'hero'})).json()
    assert any(item['id'] == asset['id'] for item in page['items'])

    # signed URLs stream the bytes without a session
    thumb = await httpx.AsyncClient(transport=client._transport, base_url='http://testserver').get(
        asset['thumb_url'].removeprefix('http://testserver')
    )
    assert thumb.status_code == 200
    assert thumb.headers['content-type'] == 'image/webp'
    assert thumb.content[:4] == b'RIFF'


async def test_documents_and_unknown_files_are_rejected(client: httpx.AsyncClient):
    res = await client.post(
        '/api/v1/media/assets', files={'file': ('offer.pdf', b'%PDF-1.7 hello world', 'application/pdf')}
    )
    assert res.status_code == 415
    assert res.json()['extra']['code'] == 'document_not_media'
    res = await client.post('/api/v1/media/assets', files={'file': ('fake.png', b'not an image at all!!', 'image/png')})
    assert res.status_code == 415


async def test_svg_is_sanitized(client: httpx.AsyncClient):
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" onload="alert(1)"><script>alert(2)</script><rect width="10" height="10"/></svg>'
    res = await client.post('/api/v1/media/assets', files={'file': ('logo.svg', svg, 'image/svg+xml')})
    assert res.status_code == 201, res.text
    asset = res.json()
    assert (asset['width'], asset['height']) == (10, 10)
    body = (await client.get(asset['url'].removeprefix('http://testserver'))).content
    assert b'script' not in body and b'onload' not in body and b'<rect' in body


async def test_edit_favorite_folder_trash_restore_purge(client: httpx.AsyncClient):
    asset = (await _upload(client, 'team.png')).json()
    aid = asset['id']

    folder = (await client.post('/api/v1/media/folders/', json={'name': 'Campaign'})).json()
    dup = await client.post('/api/v1/media/folders/', json={'name': 'campaign'})
    assert dup.status_code == 409

    res = await client.patch(
        f'/api/v1/media/assets/{aid}', json={'title': 'Our team', 'alt': 'The team', 'focal_x': 0.3, 'folder_id': folder['id']}
    )
    assert res.status_code == 200, res.text
    assert res.json()['folder_id'] == folder['id'] and res.json()['focal_x'] == 0.3
    assert (await client.patch(f'/api/v1/media/assets/{aid}', json={'focal_y': 2})).status_code == 400

    assert (await client.put(f'/api/v1/media/assets/{aid}/favorite')).status_code == 204
    favs = (await client.get('/api/v1/media/assets', params={'tab': 'favorites'})).json()
    assert [i['id'] for i in favs['items']] == [aid] and favs['items'][0]['favorite'] is True

    in_folder = (await client.get('/api/v1/media/assets', params={'folder_id': folder['id']})).json()
    assert [i['id'] for i in in_folder['items']] == [aid]
    folders = (await client.get('/api/v1/media/folders/')).json()
    assert next(f for f in folders if f['id'] == folder['id'])['asset_count'] == 1

    # deleting the folder moves its files up
    assert (await client.delete(f'/api/v1/media/folders/{folder["id"]}')).status_code == 204
    assert (await client.get(f'/api/v1/media/assets/{aid}')).json().get('folder_id') is None

    assert (await client.delete(f'/api/v1/media/assets/{aid}')).status_code == 204
    trash = (await client.get('/api/v1/media/assets', params={'tab': 'trash'})).json()
    assert aid in [i['id'] for i in trash['items']]
    assert (await client.post(f'/api/v1/media/assets/{aid}/restore')).status_code == 200
    assert (await client.delete(f'/api/v1/media/assets/{aid}')).status_code == 204
    assert (await client.delete(f'/api/v1/media/assets/{aid}', params={'permanent': 'true'})).status_code == 204
    assert (await client.get(f'/api/v1/media/assets/{aid}')).status_code == 404


async def test_replace_keeps_the_id_and_resolve_lists_variants(client: httpx.AsyncClient):
    asset = (await _upload(client, 'banner.png', _png(400, 200))).json()
    res = await client.put(
        f'/api/v1/media/assets/{asset["id"]}/file', files={'file': ('banner-v2.png', _png(1600, 800, 'tomato'), 'image/png')}
    )
    assert res.status_code == 200, res.text
    replaced = res.json()
    assert replaced['id'] == asset['id'] and replaced['width'] == 1600 and replaced['url'] != asset['url']

    resolved = (await client.post('/api/v1/media/assets/resolve', json={'ids': [asset['id']]})).json()['items']
    assert resolved[0]['width'] == 1600
    assert {s['width'] for s in resolved[0]['sources']} >= {320, 640, 1280}

    storage = (await client.get('/api/v1/media/storage')).json()
    assert storage['used'] > 0 and storage['count'] >= 1


async def test_the_library_is_per_organization(client: httpx.AsyncClient, test_org):
    asset = (await _upload(client, 'parent.png')).json()
    child = {'X-Organization-Id': str(test_org.child_organization_id)}
    assert (await client.get(f'/api/v1/media/assets/{asset["id"]}', headers=child)).status_code == 404
    listing = (await client.get('/api/v1/media/assets', headers=child)).json()
    assert asset['id'] not in [i['id'] for i in listing['items']]


async def test_signed_out_is_401(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as anonymous:
        assert (await anonymous.get('/api/v1/media/assets')).status_code == 401
        assert (await anonymous.get('/api/v1/media/files/forged.token')).status_code == 404
