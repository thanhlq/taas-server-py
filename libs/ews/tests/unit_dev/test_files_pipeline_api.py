"""File Manager processing pipeline and delivery end to end on the local database (memory storage): thumbnails,
previews, local full-text index (search by content), cached / revocable signed URLs, byte ranges, checksum of direct
uploads, purge of derived objects (taas-specs/files File-0302, File-0400, File-0500 … File-0605).

The pipeline is driven by the test (``ews.files.drain``). A development API running on the same database with
``FILES_PIPELINE=api`` may claim a version first and find no object (it does not share this in-memory storage):
``_ready`` detects it and queues the version again.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import uuid
import zipfile

import httpx
import pytest
from PIL import Image

FILES = '/api/v1/files'


@pytest.fixture(scope='module', autouse=True)
def files_storage(app, test_org):
    """An in-memory private storage of this module (put back afterwards)."""
    from blob_service import (
        MemoryBlobAdapter,
        MemoryTenantBucketRegistry,
        create_blob_service,
        create_storage_resolver,
    )
    from ews.files._delivery import forget_link_states, forget_urls
    from ews.shared import use_storage
    from foundation.blob import StorageSettings

    adapter = MemoryBlobAdapter()
    registry = MemoryTenantBucketRegistry({str(test_org.tenant_id): '12345678'})
    blob = create_blob_service(adapter=adapter, registry=registry, register=False)
    settings = StorageSettings(
        STORAGE_PRIVATE_MODE='pooled',
        STORAGE_PRIVATE_BUCKET='taas-private-pipeline-test',
    )
    resolver = create_storage_resolver(blob, registry, settings, register=False)
    previous = use_storage(resolver)
    forget_urls()
    forget_link_states()
    yield resolver
    use_storage(previous)
    forget_urls()


# --- samples --------------------------------------------------------------------------------------


def _png(size: tuple[int, int] = (2400, 1600), color: str = 'teal') -> bytes:
    out = io.BytesIO()
    Image.new('RGB', size, color).save(out, 'PNG')
    return out.getvalue()


def _pdf(words: str) -> bytes:
    stream = f'BT /F1 24 Tf 72 720 Td ({words}) Tj ET'.encode()
    objects = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R '
        b'/Resources << /Font << /F1 5 0 R >> >> >>',
        b'<< /Length %d >>\nstream\n' % len(stream) + stream + b'\nendstream',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    ]
    out = io.BytesIO()
    out.write(b'%PDF-1.4\n')
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(b'%d 0 obj\n' % number + body + b'\nendobj\n')
    xref = out.tell()
    out.write(b'xref\n0 %d\n0000000000 65535 f \n' % (len(objects) + 1))
    for offset in offsets:
        out.write(b'%010d 00000 n \n' % offset)
    out.write(
        b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n'
        % (len(objects) + 1, xref)
    )
    return out.getvalue()


def _docx(text: str) -> bytes:
    out = io.BytesIO()
    cover = io.BytesIO()
    Image.new('RGB', (200, 280), 'white').save(cover, 'JPEG')
    with zipfile.ZipFile(out, 'w') as archive:
        archive.writestr('[Content_Types].xml', '<Types/>')
        archive.writestr(
            'word/document.xml',
            f'<w:document><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>',
        )
        archive.writestr('docProps/thumbnail.jpeg', cover.getvalue())
    return out.getvalue()


# --- helpers --------------------------------------------------------------------------------------


async def _shared_drive(client: httpx.AsyncClient, name: str) -> str:
    res = await client.post(
        f'{FILES}/drives/', json={'name': f'{name} {uuid.uuid4().hex[:6]}'}
    )
    assert res.status_code == 201, res.text
    return res.json()['id']


async def _upload(
    client: httpx.AsyncClient, drive_id: str, name: str, body: bytes, mime: str
) -> dict:
    res = await client.post(
        f'{FILES}/drives/{drive_id}/files', files={'file': (name, body, mime)}
    )
    assert res.status_code == 201, res.text
    return res.json()['node']


async def _ready(client: httpx.AsyncClient, tenant_id: uuid.UUID, node_id: str) -> dict:
    """Run the pipeline until the current version is processed; returns that version."""
    from ews.files import drain

    for _ in range(6):
        await drain(tenant_id=tenant_id)
        current = (await client.get(f'{FILES}/nodes/{node_id}/versions')).json()[0]
        status = current.get('pipeline_status', 'pending')
        if (
            status == 'done'
            and current.get('pipeline_error') != 'object missing in storage'
        ):
            return current
        if status in (
            'done',
            'failed',
        ):  # taken by another process on this database: queue it again
            assert (
                await client.post(f'{FILES}/nodes/{node_id}/reprocess')
            ).status_code == 202
        await asyncio.sleep(0.2)
    raise AssertionError(f'version of {node_id} not processed: {current}')


async def _fetch(client: httpx.AsyncClient, url: str, **headers: str) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=client._transport, base_url='http://testserver'
    ) as anon:
        return await anon.get(url.removeprefix('http://testserver'), headers=headers)


async def _listed(client: httpx.AsyncClient, drive_id: str, node_id: str) -> dict:
    items = (await client.get(f'{FILES}/drives/{drive_id}/nodes')).json()['items']
    return next(i for i in items if i['id'] == node_id)


# --- previews -------------------------------------------------------------------------------------


async def test_file_0302_image_thumbnail_preview_and_cached_view_urls(
    client: httpx.AsyncClient, test_org
):
    drive = await _shared_drive(client, 'Photos')
    node = await _upload(client, drive, 'skyline.png', _png(), 'image/png')
    assert node['preview_status'] == 'pending' and 'thumbnail_url' not in node
    version = await _ready(client, test_org.tenant_id, node['id'])
    assert version['preview_status'] == 'ready' and version['index_status'] == 'none'
    assert version['meta'] == {'sniffed': 'image/png', 'width': 2400, 'height': 1600}

    listed = await _listed(client, drive, node['id'])
    assert listed['preview_status'] == 'ready'
    assert listed['placeholder'].startswith('data:image/webp;base64,')
    again = await _listed(client, drive, node['id'])
    assert (
        again['thumbnail_url'] == listed['thumbnail_url']
    )  # File-0501: same URL within a window

    thumb = await _fetch(client, listed['thumbnail_url'])
    assert thumb.status_code == 200 and thumb.headers['content-type'] == 'image/webp'
    assert thumb.content[8:12] == b'WEBP'
    cache = thumb.headers['cache-control']
    assert cache.startswith('private, max-age=') and cache.endswith('immutable')
    assert (
        int(cache.split('max-age=')[1].split(',')[0]) > 17 * 3600
    )  # 24 h window, rounded
    cached = await _fetch(
        client, listed['thumbnail_url'], **{'If-None-Match': thumb.headers['etag']}
    )
    assert cached.status_code == 304 and cached.content == b''

    preview = (await client.get(f'{FILES}/nodes/{node["id"]}/preview')).json()
    assert preview['kind'] == 'image' and preview['mime'] == 'image/webp'
    assert (preview['width'], preview['height']) == (
        1920,
        1280,
    )  # rendition, not the 2400 px original
    assert preview['url'] != preview['thumbnail_url'] and preview['status'] == 'ready'
    assert (await _fetch(client, preview['url'])).status_code == 200
    actions = [
        a['action']
        for a in (await client.get(f'{FILES}/nodes/{node["id"]}/activity')).json()
    ]
    assert 'file.previewed' in actions


async def test_file_0302_pdf_office_and_text_previews(
    client: httpx.AsyncClient, test_org
):
    drive = await _shared_drive(client, 'Documents')
    pdf = await _upload(
        client, drive, 'invoice.pdf', _pdf('Invoice gondolier'), 'application/pdf'
    )
    docx = await _upload(
        client,
        drive,
        'offer.docx',
        _docx('Offer narwhal'),
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    )
    note = await _upload(
        client, drive, 'note.md', b'# Title\n\nSome *markdown*', 'text/markdown'
    )
    pdf_version = await _ready(client, test_org.tenant_id, pdf['id'])
    assert pdf_version['meta']['pages'] == 1 and pdf_version['index_status'] == 'ready'
    for node in (docx, note):
        await _ready(client, test_org.tenant_id, node['id'])

    pdf_preview = (await client.get(f'{FILES}/nodes/{pdf["id"]}/preview')).json()
    assert pdf_preview['kind'] == 'pdf' and pdf_preview['mime'] == 'application/pdf'
    assert (
        pdf_preview['thumbnail_url']
        and pdf_preview['url'] != pdf_preview['thumbnail_url']
    )
    opened = await _fetch(client, pdf_preview['url'])
    assert opened.status_code == 200 and opened.content.startswith(b'%PDF')
    assert opened.headers['content-disposition'].startswith('inline;')

    cover = (await client.get(f'{FILES}/nodes/{docx["id"]}/preview')).json()
    assert (
        cover['kind'] == 'image' and cover['url'] == cover['thumbnail_url']
    )  # Office: its embedded cover

    text = (await client.get(f'{FILES}/nodes/{note["id"]}/preview')).json()
    assert (
        text['kind'] == 'text'
        and text['status'] == 'none'
        and 'thumbnail_url' not in text
    )
    assert (await _fetch(client, text['url'])).text.startswith('# Title')


# --- local index ----------------------------------------------------------------------------------


async def test_file_0400_search_by_content_with_snippets(
    client: httpx.AsyncClient, test_org
):
    drive = await _shared_drive(client, 'Index')
    word = f'zebracorn{uuid.uuid4().hex[:6]}'
    node = await _upload(
        client,
        drive,
        'minutes.txt',
        f'The board met.\nThe {word} plan was approved.'.encode(),
        'text/plain',
    )
    pdf = await _upload(
        client, drive, 'scan.pdf', _pdf(f'Annex {word}'), 'application/pdf'
    )
    for item in (node, pdf):
        await _ready(client, test_org.tenant_id, item['id'])

    page = (
        await client.get(f'{FILES}/search', params={'q': word[:-2], 'drive_id': drive})
    ).json()
    hits = {h['id']: h for h in page['items']}
    assert set(hits) == {node['id'], pdf['id']} and page['total'] == 2
    assert hits[node['id']]['match'] == 'content'
    assert (
        f'\x02{word}\x03' in hits[node['id']]['snippet']
        and 'approved' in hits[node['id']]['snippet']
    )
    assert hits[pdf['id']]['rank'] > 0
    by_name = (
        await client.get(
            f'{FILES}/search', params={'q': word, 'match': 'name', 'drive_id': drive}
        )
    ).json()
    assert by_name['items'] == []
    named = (
        await client.get(f'{FILES}/search', params={'q': 'minutes', 'drive_id': drive})
    ).json()
    assert [(h['id'], h.get('match', 'name')) for h in named['items']] == [
        (node['id'], 'name')
    ]

    # Only the current version is searchable.
    res = await client.post(
        f'{FILES}/nodes/{node["id"]}/versions',
        files={'file': ('minutes.txt', b'Only pelicans now', 'text/plain')},
    )
    assert res.status_code == 201, res.text
    await _ready(client, test_org.tenant_id, node['id'])
    page = (
        await client.get(f'{FILES}/search', params={'q': word, 'drive_id': drive})
    ).json()
    assert [h['id'] for h in page['items']] == [pdf['id']]
    page = (
        await client.get(f'{FILES}/search', params={'q': 'pelicans', 'drive_id': drive})
    ).json()
    assert [h['id'] for h in page['items']] == [node['id']]

    # Trashed items leave the results.
    assert (await client.delete(f'{FILES}/nodes/{pdf["id"]}')).status_code == 204
    page = (
        await client.get(f'{FILES}/search', params={'q': word, 'drive_id': drive})
    ).json()
    assert page['items'] == []


# --- delivery -------------------------------------------------------------------------------------


async def test_file_0502_byte_ranges_and_short_lived_downloads(
    client: httpx.AsyncClient, test_org
):
    drive = await _shared_drive(client, 'Ranges')
    node = await _upload(client, drive, 'abc.txt', b'abcdefghij', 'text/plain')
    view = (
        await client.get(
            f'{FILES}/nodes/{node["id"]}/download', params={'inline': 'true'}
        )
    ).json()
    part = await _fetch(client, view['url'], Range='bytes=2-4')
    assert part.status_code == 206 and part.content == b'cde'
    assert part.headers['content-range'] == 'bytes 2-4/10'
    assert (await _fetch(client, view['url'], Range='bytes=50-')).status_code == 416
    download = (await client.get(f'{FILES}/nodes/{node["id"]}/download')).json()
    res = await _fetch(client, download['url'])
    assert res.headers['cache-control'] == 'private, no-store'
    assert res.headers['content-disposition'].startswith('attachment;')


async def test_file_0503_signed_urls_are_revocable(client: httpx.AsyncClient, test_org):
    drive = await _shared_drive(client, 'Revoke')
    node = await _upload(client, drive, 'map.png', _png((64, 64)), 'image/png')
    await _ready(client, test_org.tenant_id, node['id'])
    url = (await _listed(client, drive, node['id']))['thumbnail_url']
    assert (await _fetch(client, url)).status_code == 200

    # A trashed item's URLs stop working; restored, they work again.
    assert (await client.delete(f'{FILES}/nodes/{node["id"]}')).status_code == 204
    assert (await _fetch(client, url)).status_code == 404
    assert (await client.post(f'{FILES}/nodes/{node["id"]}/restore')).status_code == 200
    assert (await _fetch(client, url)).status_code == 200

    # Revoke links: every URL handed out so far is dead, new ones work.
    assert (
        await client.post(f'{FILES}/drives/{drive}/links/revoke')
    ).status_code == 204
    assert (await _fetch(client, url)).status_code == 404
    fresh = (await _listed(client, drive, node['id']))['thumbnail_url']
    assert fresh != url and (await _fetch(client, fresh)).status_code == 200
    actions = [
        a['action']
        for a in (await client.get(f'{FILES}/drives/{drive}/activity')).json()
    ]
    assert 'drive.links_revoked' in actions

    # Confidential drive: short-lived, never cached, and the switch revokes the standard URLs.
    res = await client.patch(
        f'{FILES}/drives/{drive}', json={'sensitivity': 'confidential'}
    )
    assert res.status_code == 200 and res.json()['sensitivity'] == 'confidential'
    assert (await _fetch(client, fresh)).status_code == 404
    preview = (await client.get(f'{FILES}/nodes/{node["id"]}/preview')).json()
    thumb = await _fetch(client, preview['thumbnail_url'])
    assert (
        thumb.status_code == 200
        and thumb.headers['cache-control'] == 'private, no-store'
    )
    assert (
        await client.patch(f'{FILES}/drives/{drive}', json={'sensitivity': 'secret'})
    ).status_code in (400, 422)


# --- pipeline -------------------------------------------------------------------------------------


async def test_file_0600_direct_uploads_get_a_checksum_and_reprocess(
    client: httpx.AsyncClient, test_org
):
    drive = await _shared_drive(client, 'Direct')
    body = _png((32, 32), 'orange')
    ticket = (
        await client.post(
            f'{FILES}/drives/{drive}/uploads',
            json={'name': 'logo.png', 'size': len(body)},
        )
    ).json()
    put = await _fetch_put(client, ticket['url'], body, ticket['headers'])
    assert put.status_code == 204
    done = (
        await client.post(f'{FILES}/uploads/complete', json={'token': ticket['token']})
    ).json()
    node_id = done['node']['id']
    assert (
        'checksum'
        not in (await client.get(f'{FILES}/nodes/{node_id}/versions')).json()[0]
    )
    version = await _ready(client, test_org.tenant_id, node_id)
    assert version['checksum'] == hashlib.sha256(body).hexdigest()

    res = await client.post(f'{FILES}/nodes/{node_id}/reprocess')
    assert res.status_code == 202 and res.json()['preview_status'] == 'pending'
    assert (await _ready(client, test_org.tenant_id, node_id))[
        'preview_status'
    ] == 'ready'
    folder = (
        await client.post(f'{FILES}/drives/{drive}/folders', json={'name': 'Box'})
    ).json()
    assert (
        await client.post(f'{FILES}/nodes/{folder["id"]}/reprocess')
    ).status_code == 400


async def test_file_0604_purge_removes_generated_objects(
    client: httpx.AsyncClient, test_org, files_storage
):
    drive = await _shared_drive(client, 'Purge')
    node = await _upload(client, drive, 'big.png', _png(), 'image/png')
    await _ready(client, test_org.tenant_id, node['id'])
    store = await files_storage.root(test_org.tenant_id)
    from foundation.blob import BlobListOptions

    prefix = f'derived/files/{node["id"]}/'
    assert (
        len((await store.list(BlobListOptions(prefix=prefix))).items) == 2
    )  # thumb + preview
    assert (await client.delete(f'{FILES}/nodes/{node["id"]}')).status_code == 204
    assert (
        await client.delete(f'{FILES}/nodes/{node["id"]}', params={'permanent': 'true'})
    ).status_code == 204
    assert (await store.list(BlobListOptions(prefix=prefix))).items == []


async def test_file_0605_concurrent_runners_never_process_a_version_twice(
    client: httpx.AsyncClient, test_org
):
    from ews.files import drain

    drive = await _shared_drive(client, 'Concurrency')
    nodes = [
        await _upload(client, drive, f'p{i}.png', _png((40 + i, 40)), 'image/png')
        for i in range(4)
    ]
    await asyncio.gather(
        drain(tenant_id=test_org.tenant_id), drain(tenant_id=test_org.tenant_id)
    )
    for node in nodes:
        assert (await _ready(client, test_org.tenant_id, node['id']))[
            'preview_status'
        ] == 'ready'


async def _fetch_put(
    client: httpx.AsyncClient, url: str, body: bytes, headers: dict
) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=client._transport, base_url='http://testserver'
    ) as anon:
        return await anon.put(
            url.removeprefix('http://testserver'), content=body, headers=headers
        )
