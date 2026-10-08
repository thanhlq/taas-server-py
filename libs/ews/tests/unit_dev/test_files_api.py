"""``/api/v1/files`` end to end on the local database (memory storage): drives, tree, uploads, versions, downloads,
trash, views, and the permission matrix in IAM mode (taas-specs/files/file-manager-app-spec.md File-0100 … File-0400).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta

import httpx
import pytest

FILES = '/api/v1/files'


@pytest.fixture(scope='module', autouse=True)
def files_storage(app, test_org):
    """Private storage of the File Manager: an in-memory adapter of its own for this module; the resolver set by the
    conftest (``app``, created first) is put back afterwards."""
    from blob_service import (
        MemoryBlobAdapter,
        MemoryTenantBucketRegistry,
        create_blob_service,
        create_storage_resolver,
    )
    from ews.shared import use_storage
    from foundation.blob import StorageSettings

    adapter = MemoryBlobAdapter()
    registry = MemoryTenantBucketRegistry({str(test_org.tenant_id): '12345678'})
    blob = create_blob_service(adapter=adapter, registry=registry, register=False)
    settings = StorageSettings(
        STORAGE_PRIVATE_MODE='pooled', STORAGE_PRIVATE_BUCKET='taas-private-files-test'
    )
    resolver = create_storage_resolver(blob, registry, settings, register=False)
    previous = use_storage(resolver)
    yield resolver
    use_storage(previous)


async def _upload(
    client: httpx.AsyncClient,
    drive_id: str,
    name: str,
    body: bytes = b'hello',
    mime: str = 'text/plain',
    **fields,
):
    return await client.post(
        f'{FILES}/drives/{drive_id}/files',
        files={'file': (name, body, mime)},
        data=fields,
    )


async def _drives(client: httpx.AsyncClient, **headers) -> tuple[str, str]:
    res = await client.get(f'{FILES}/access', headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    return body.get('organization_drive_id'), body['personal_drive_id']


async def _fetch(client: httpx.AsyncClient, url: str) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=client._transport, base_url='http://testserver'
    ) as anon:
        return await anon.get(url.removeprefix('http://testserver'))


# --- development mode (every permission): flows ---------------------------------------------------


async def test_file_0100_access_creates_the_organization_drive_and_my_files_once(
    client: httpx.AsyncClient,
):
    first = (await client.get(f'{FILES}/access')).json()
    assert first['allowed'] is True and first['can_create_shared_drive'] is True
    again = (await client.get(f'{FILES}/access')).json()
    assert (first['organization_drive_id'], first['personal_drive_id']) == (
        again['organization_drive_id'],
        again['personal_drive_id'],
    )
    listed = {d['id']: d for d in (await client.get(f'{FILES}/drives/')).json()}
    assert listed[first['organization_drive_id']]['kind'] == 'organization'
    assert (
        listed[first['organization_drive_id']]['default_member_role'] == 'drive_editor'
    )
    assert listed[first['personal_drive_id']]['name'] == 'My files'
    roles = (await client.get(f'{FILES}/roles')).json()
    assert [r['key'] for r in roles] == [
        'drive_manager',
        'drive_editor',
        'drive_commenter',
        'drive_viewer',
    ]
    assert [r['key'] for r in roles if r.get('default')] == ['drive_editor']


async def test_file_0300_0301_upload_conflicts_versions_and_downloads(
    client: httpx.AsyncClient,
):
    org_drive, _ = await _drives(client)
    folder = (
        await client.post(
            f'{FILES}/drives/{org_drive}/folders', json={'name': 'Contracts'}
        )
    ).json()
    assert (
        await client.post(
            f'{FILES}/drives/{org_drive}/folders', json={'name': 'contracts'}
        )
    ).status_code == 409

    res = await _upload(
        client,
        org_drive,
        'offer.txt',
        b'v1',
        parent_id=folder['id'],
        comment='first draft',
    )
    assert res.status_code == 201, res.text
    assert res.json()['result'] == 'created'
    file = res.json()['node']
    assert (file['name'], file['type'], file['version'], file['size']) == (
        'offer.txt',
        'document',
        1,
        2,
    )

    # Same name in the same folder: new version (default) · keep both · skip.
    res = await _upload(
        client, org_drive, 'OFFER.txt', b'v2 longer', parent_id=folder['id']
    )
    assert (
        res.json()['result'] == 'versioned' and res.json()['node']['id'] == file['id']
    )
    assert res.json()['node']['version'] == 2
    both = (
        await _upload(
            client,
            org_drive,
            'offer.txt',
            b'other',
            parent_id=folder['id'],
            on_conflict='keep_both',
        )
    ).json()
    assert both['result'] == 'created' and both['node']['name'] == 'offer (1).txt'
    skipped = (
        await _upload(
            client,
            org_drive,
            'offer.txt',
            b'x',
            parent_id=folder['id'],
            on_conflict='skip',
        )
    ).json()
    assert skipped['result'] == 'skipped' and skipped['node']['id'] == file['id']
    assert (
        await _upload(client, org_drive, 'Contracts', b'x')
    ).status_code == 409  # a folder has that name
    assert (
        await _upload(client, org_drive, 'bad.txt', b'x', on_conflict='merge')
    ).status_code == 400

    # A dropped folder: missing folders are created.
    nested = (
        await _upload(
            client,
            org_drive,
            'ignored',
            b'deep',
            relative_path='Q3/Reports/summary.txt',
        )
    ).json()
    assert nested['node']['name'] == 'summary.txt' and nested['node']['depth'] == 2

    page = (
        await client.get(
            f'{FILES}/drives/{org_drive}/nodes', params={'parent_id': folder['id']}
        )
    ).json()
    assert [n['name'] for n in page['items']] == [
        'offer (1).txt',
        'offer.txt',
    ] and page['total'] == 2
    in_folder = (
        await client.get(
            f'{FILES}/drives/{org_drive}/nodes',
            params={'parent_id': folder['id'], 'q': '(1)'},
        )
    ).json()
    assert [n['name'] for n in in_folder['items']] == ['offer (1).txt']

    versions = (await client.get(f'{FILES}/nodes/{file["id"]}/versions')).json()
    assert [(v['number'], v.get('current', False)) for v in versions] == [
        (2, True),
        (1, False),
    ]
    assert (
        versions[1]['comment'] == 'first draft'
        and versions[1]['scan_status'] == 'skipped'
    )
    v1 = versions[1]['id']
    res = await client.patch(
        f'{FILES}/nodes/{file["id"]}/versions/{v1}', json={'comment': 'signed copy'}
    )
    assert res.status_code == 200 and res.json()['comment'] == 'signed copy'
    restored = (
        await client.post(f'{FILES}/nodes/{file["id"]}/versions/{v1}/restore')
    ).json()
    assert restored['version'] == 3 and restored['size'] == 2
    latest = (await client.get(f'{FILES}/nodes/{file["id"]}/versions')).json()[0]
    assert latest['restored_from'] == 1
    assert (
        await client.post(f'{FILES}/nodes/{file["id"]}/versions/{latest["id"]}/restore')
    ).status_code == 409

    # Download: a short-lived signed URL streams the bytes; old versions too (File-0206, Sto-0200).
    dl = (await client.get(f'{FILES}/nodes/{file["id"]}/download')).json()
    assert dl['inline'] is False and dl['filename'] == 'offer.txt'
    got = await _fetch(client, dl['url'])
    assert got.status_code == 200 and got.content == b'v1'
    assert got.headers['content-disposition'].startswith('attachment;')
    assert got.headers['x-content-type-options'] == 'nosniff'
    old = (
        await client.get(
            f'{FILES}/nodes/{file["id"]}/download',
            params={'version_id': versions[0]['id']},
        )
    ).json()
    assert (await _fetch(client, old['url'])).content == b'v2 longer'
    assert (await _fetch(client, dl['url'] + 'x')).status_code == 404

    # Inline only for safe types: a text preview is inline, an HTML page is downloaded.
    preview = (
        await client.get(
            f'{FILES}/nodes/{file["id"]}/download', params={'inline': True}
        )
    ).json()
    assert preview['inline'] is True
    assert (
        (await _fetch(client, preview['url']))
        .headers['content-disposition']
        .startswith('inline;')
    )
    html = (
        await _upload(
            client, org_drive, 'page.html', b'<script>alert(1)</script>', 'text/html'
        )
    ).json()['node']
    risky = (
        await client.get(
            f'{FILES}/nodes/{html["id"]}/download', params={'inline': True}
        )
    ).json()
    assert risky['inline'] is False and risky['mime'] == 'text/html'

    detail = (await client.get(f'{FILES}/nodes/{nested["node"]["id"]}')).json()
    assert [a['name'] for a in detail['ancestors']] == ['Q3', 'Reports']
    assert 'files.item:update' in detail['permissions']
    actions = [
        a['action']
        for a in (await client.get(f'{FILES}/nodes/{file["id"]}/activity')).json()
    ]
    assert {
        'file.uploaded',
        'file.version',
        'file.version_restored',
        'file.downloaded',
        'file.previewed',
    } <= set(actions)
    folder_actions = {
        a['action']
        for a in (await client.get(f'{FILES}/nodes/{folder["id"]}/activity')).json()
    }
    assert {
        'folder.created',
        'file.uploaded',
    } <= folder_actions  # a folder's activity includes its subtree


async def test_file_0300_direct_upload_through_the_proxy(client: httpx.AsyncClient):
    _, personal = await _drives(client)
    body = b'direct bytes' * 10
    ticket = (
        await client.post(
            f'{FILES}/drives/{personal}/uploads',
            json={'name': 'direct.txt', 'size': len(body)},
        )
    ).json()
    assert ticket['url'].startswith(
        'http://testserver/api/v1/files/uploads/'
    ) and ticket['headers'] == {'content-type': 'text/plain'}
    assert (
        await client.post(f'{FILES}/uploads/complete', json={'token': ticket['token']})
    ).json()['extra']['code'] == 'upload_missing'
    async with httpx.AsyncClient(
        transport=client._transport, base_url='http://testserver'
    ) as anon:
        put = await anon.put(
            ticket['url'].removeprefix('http://testserver'),
            content=body,
            headers=ticket['headers'],
        )
        assert put.status_code == 204, put.text
        assert (
            await anon.put('/api/v1/files/uploads/forged.token', content=b'x')
        ).status_code == 404
    done = await client.post(
        f'{FILES}/uploads/complete',
        json={'token': ticket['token'], 'comment': 'from the browser'},
    )
    assert done.status_code == 201, done.text
    node = done.json()['node']
    assert done.json()['result'] == 'created' and node['size'] == len(body)
    again = await client.post(
        f'{FILES}/uploads/complete', json={'token': ticket['token']}
    )
    assert again.json()['node']['id'] == node['id']  # idempotent
    dl = (await client.get(f'{FILES}/nodes/{node["id"]}/download')).json()
    assert (await _fetch(client, dl['url'])).content == body

    # New version of that file, then a size that does not match the ticket.
    ticket = (
        await client.post(
            f'{FILES}/drives/{personal}/uploads',
            json={'name': 'x', 'size': 3, 'node_id': node['id']},
        )
    ).json()
    async with httpx.AsyncClient(
        transport=client._transport, base_url='http://testserver'
    ) as anon:
        assert (
            await anon.put(
                ticket['url'].removeprefix('http://testserver'), content=b'abcd'
            )
        ).status_code == 413
        await anon.put(ticket['url'].removeprefix('http://testserver'), content=b'abc')
    done = (
        await client.post(f'{FILES}/uploads/complete', json={'token': ticket['token']})
    ).json()
    assert done['result'] == 'versioned' and done['node']['version'] == 2

    skip = (
        await client.post(
            f'{FILES}/drives/{personal}/uploads',
            json={'name': 'direct.txt', 'size': 1, 'on_conflict': 'skip'},
        )
    ).json()
    assert skip['skipped'] is True and skip['node']['id'] == node['id']
    too_big = await client.post(
        f'{FILES}/drives/{personal}/uploads', json={'name': 'big.bin', 'size': 10**12}
    )
    assert too_big.status_code == 413
    assert (
        await client.post(f'{FILES}/uploads/complete', json={'token': 'nope'})
    ).status_code == 400


async def test_file_0303_rename_move_copy_star_and_depth(client: httpx.AsyncClient):
    org_drive, personal = await _drives(client)
    a = (
        await client.post(
            f'{FILES}/drives/{org_drive}/folders',
            json={'name': 'Move A', 'color': '#112233'},
        )
    ).json()
    b = (
        await client.post(
            f'{FILES}/drives/{org_drive}/folders',
            json={'name': 'Move B', 'parent_id': a['id']},
        )
    ).json()
    f = (await _upload(client, org_drive, 'moving.txt', parent_id=b['id'])).json()[
        'node'
    ]
    other = (
        await client.post(
            f'{FILES}/drives/{personal}/folders', json={'name': 'Elsewhere'}
        )
    ).json()

    assert (
        await client.patch(f'{FILES}/nodes/{f["id"]}', json={'name': 'Moved.md'})
    ).json()['ext'] == 'md'
    clash = (await _upload(client, org_drive, 'clash.txt', parent_id=b['id'])).json()[
        'node'
    ]
    assert (
        await client.patch(f'{FILES}/nodes/{clash["id"]}', json={'name': 'moved.MD'})
    ).status_code == 409
    assert (
        await client.patch(f'{FILES}/nodes/{f["id"]}', json={'name': 'a/b'})
    ).status_code == 400

    assert (
        await client.post(f'{FILES}/nodes/{a["id"]}/move', json={'parent_id': b['id']})
    ).status_code == 400  # into itself
    assert (
        await client.post(
            f'{FILES}/nodes/{f["id"]}/move', json={'parent_id': other['id']}
        )
    ).status_code == 400  # other drive
    moved = await client.post(f'{FILES}/nodes/{b["id"]}/move', json={'parent_id': None})
    assert moved.status_code == 200 and moved.json().get('depth', 0) == 0
    assert (await client.get(f'{FILES}/nodes/{f["id"]}')).json()[
        'depth'
    ] == 1  # subtree paths rewritten

    copy = (await client.post(f'{FILES}/nodes/{f["id"]}/copy', json={})).json()
    assert (
        copy['name'] == 'Moved (1).md'
        and copy['version'] == 1
        and copy['parent_id'] == b['id']
    )
    dl = (await client.get(f'{FILES}/nodes/{copy["id"]}/download')).json()
    assert (await _fetch(client, dl['url'])).content == b'hello'
    assert (
        await client.post(f'{FILES}/nodes/{a["id"]}/copy', json={})
    ).status_code == 400

    assert (await client.put(f'{FILES}/nodes/{f["id"]}/star')).status_code == 204
    assert (
        await client.put(f'{FILES}/nodes/{f["id"]}/star')
    ).status_code == 204  # idempotent
    starred = (await client.get(f'{FILES}/starred')).json()
    assert (
        [n['id'] for n in starred] == [f['id']]
        and starred[0]['starred'] is True
        and starred[0]['drive_name']
    )
    assert (await client.delete(f'{FILES}/nodes/{f["id"]}/star')).status_code == 204
    assert (await client.get(f'{FILES}/starred')).json() == []

    # 20 levels at most.
    parent = None
    for level in range(20):
        res = await client.post(
            f'{FILES}/drives/{personal}/folders',
            json={'name': f'L{level}', 'parent_id': parent},
        )
        assert res.status_code == 201, (level, res.text)
        parent = res.json()['id']
    too_deep = await client.post(
        f'{FILES}/drives/{personal}/folders', json={'name': 'L20', 'parent_id': parent}
    )
    assert (
        too_deep.status_code == 400 and too_deep.json()['extra']['code'] == 'too_deep'
    )


async def test_file_0306_trash_restore_and_purge(client: httpx.AsyncClient, test_org):
    org_drive, _ = await _drives(client)
    top = (
        await client.post(
            f'{FILES}/drives/{org_drive}/folders', json={'name': 'Trash me'}
        )
    ).json()
    child = (
        await client.post(
            f'{FILES}/drives/{org_drive}/folders',
            json={'name': 'Inner', 'parent_id': top['id']},
        )
    ).json()
    f = (
        await _upload(
            client, org_drive, 'inner.txt', b'gone soon', parent_id=child['id']
        )
    ).json()['node']

    assert (await client.delete(f'{FILES}/nodes/{top["id"]}')).status_code == 204
    assert (
        await client.get(
            f'{FILES}/drives/{org_drive}/nodes', params={'parent_id': top['id']}
        )
    ).status_code == 400
    assert (await client.get(f'{FILES}/nodes/{f["id"]}/download')).status_code == 404
    trash = (await client.get(f'{FILES}/drives/{org_drive}/trash')).json()
    assert [n['id'] for n in trash['items']] == [top['id']]  # the subtree is not listed
    res = await client.post(f'{FILES}/nodes/{child["id"]}/restore')
    assert res.status_code == 400 and res.json()['extra']['code'] == 'not_trash_root'
    assert (
        await client.delete(f'{FILES}/nodes/{f["id"]}', params={'permanent': True})
    ).status_code == 400

    # The name was taken meanwhile: restored as "Trash me (1)".
    await client.post(f'{FILES}/drives/{org_drive}/folders', json={'name': 'Trash me'})
    restored = (await client.post(f'{FILES}/nodes/{top["id"]}/restore')).json()
    assert restored['name'] == 'Trash me (1)' and restored.get('trashed_at') is None
    assert (await client.get(f'{FILES}/nodes/{f["id"]}')).status_code == 200

    # The parent is gone: the item comes back at the top level.
    assert (await client.delete(f'{FILES}/nodes/{child["id"]}')).status_code == 204
    assert (await client.delete(f'{FILES}/nodes/{top["id"]}')).status_code == 204
    back = (await client.post(f'{FILES}/nodes/{child["id"]}/restore')).json()
    assert back.get('parent_id') is None and back.get('depth', 0) == 0

    # Delete for good: storage objects removed, the activity kept.
    from ews.shared import tenant_root

    versions = (await client.get(f'{FILES}/nodes/{f["id"]}/versions')).json()
    assert (await client.delete(f'{FILES}/nodes/{child["id"]}')).status_code == 204
    assert (
        await client.delete(f'{FILES}/nodes/{child["id"]}', params={'permanent': True})
    ).status_code == 204
    assert (await client.get(f'{FILES}/nodes/{f["id"]}')).status_code == 404
    from foundation.blob import BlobListOptions

    keys = [
        i.key
        for i in (
            await (await tenant_root(test_org.tenant_id)).list(
                BlobListOptions(prefix='documents/')
            )
        ).items
    ]
    assert keys and not [k for k in keys if versions[0]['id'] in k]
    assert 'node.purged' in {
        a['action']
        for a in (await client.get(f'{FILES}/drives/{org_drive}/activity')).json()
    }

    # Retention: the trash is purged after FILES_TRASH_DAYS (worker wiring 🚧).
    from ews.files import purge_expired
    from ews.shared import utcnow
    from foundation.db.advanced_db_manager import MainDatabase
    from sqlalchemy.ext.asyncio import AsyncSession

    async with AsyncSession(MainDatabase.get_instance().get_engine()) as session:
        assert await purge_expired(session, days=30, tenant_id=test_org.tenant_id) == 0
        purged = await purge_expired(
            session,
            days=30,
            now=utcnow() + timedelta(days=31),
            tenant_id=test_org.tenant_id,
        )
        await session.commit()
    assert purged >= 1
    assert (await client.get(f'{FILES}/nodes/{top["id"]}')).status_code == 404


async def test_file_0400_search_recent_home(client: httpx.AsyncClient):
    org_drive, personal = await _drives(client)
    await _upload(
        client, org_drive, 'Quarterly budget 2026.pdf', b'%PDF-1.7', 'application/pdf'
    )
    await _upload(client, personal, 'budget_notes.txt')
    await _upload(client, personal, 'holiday.png', b'\x89PNG\r\n\x1a\n', 'image/png')
    found = (await client.get(f'{FILES}/search', params={'q': 'budget'})).json()
    assert {n['name'] for n in found['items']} >= {
        'Quarterly budget 2026.pdf',
        'budget_notes.txt',
    }
    docs = (
        await client.get(
            f'{FILES}/search',
            params={'q': 'budget', 'type': 'document', 'drive_id': org_drive},
        )
    ).json()
    assert [n['name'] for n in docs['items']] == ['Quarterly budget 2026.pdf']
    images = (
        await client.get(f'{FILES}/search', params={'type': 'image', 'owner': 'me'})
    ).json()
    assert 'holiday.png' in [n['name'] for n in images['items']]
    assert (await client.get(f'{FILES}/search', params={'q': '%'})).json()[
        'total'
    ] == 0  # LIKE wildcards escaped
    assert (
        await client.get(f'{FILES}/search', params={'drive_id': str(uuid.uuid4())})
    ).status_code == 404
    recent = (await client.get(f'{FILES}/recent', params={'limit': 5})).json()
    assert recent and all(n['kind'] == 'file' for n in recent)
    home = (await client.get(f'{FILES}/home')).json()
    assert {d['kind'] for d in home['drives']} >= {'organization', 'personal'} and home[
        'recent'
    ]


async def test_file_0100_shared_drives_crud(client: httpx.AsyncClient, test_org):
    created = await client.post(
        f'{FILES}/drives/', json={'name': 'Sales EMEA', 'color': 'blue'}
    )
    assert created.status_code == 201, created.text
    drive = created.json()
    assert drive['kind'] == 'shared' and drive['organization_id'] == str(
        test_org.organization_id
    )
    res = await client.patch(
        f'{FILES}/drives/{drive["id"]}',
        json={'name': 'Sales Europe', 'default_member_role': 'drive_viewer'},
    )
    assert res.status_code == 400  # default role: organization drives only
    assert (
        await client.patch(
            f'{FILES}/drives/{drive["id"]}', json={'name': 'Sales Europe'}
        )
    ).json()['name'] == 'Sales Europe'
    org_drive, personal = await _drives(client)
    assert (await client.delete(f'{FILES}/drives/{org_drive}')).status_code == 400
    assert (
        await client.patch(f'{FILES}/drives/{personal}', json={'name': 'Mine'})
    ).status_code == 400
    assert (
        await client.put(
            f'{FILES}/drives/{personal}/members',
            json={'user_id': str(test_org.user_id), 'role': 'drive_viewer'},
        )
    ).status_code == 400
    assert (await client.delete(f'{FILES}/drives/{drive["id"]}')).status_code == 204
    assert (await client.get(f'{FILES}/drives/{drive["id"]}')).status_code == 404
    assert drive['id'] not in [
        d['id'] for d in (await client.get(f'{FILES}/drives/')).json()
    ]
    assert (await client.get(f'{FILES}/drives/not-a-uuid')).status_code == 404
    assert (await client.get(f'{FILES}/nodes/{uuid.uuid4()}')).status_code == 404


# --- IAM mode: permission matrix (File-0200, File-0201, File-0206, File-0306) -----------------------


@dataclass(frozen=True)
class Person:
    user_id: uuid.UUID
    sub: str


@dataclass(frozen=True)
class People:
    admin: Person
    """``org_admin`` of the root organization."""
    member: Person
    """``org_member`` of the root organization (direct member)."""
    child: Person
    """``org_member`` of the child organization only."""
    sibling_org: uuid.UUID
    """Another sub-organization of the root (``/root/sibling/``)."""


async def _sql(statement: str, params: dict | None = None) -> None:
    from foundation.db.advanced_db_manager import MainDatabase
    from sqlalchemy import text

    async with MainDatabase.get_instance().get_engine().begin() as conn:
        await conn.execute(text(statement), params or {})


@pytest.fixture(scope='module')
async def people(test_org) -> AsyncIterator[People]:
    from ews.authz import grant

    sql = _sql
    persons: list[Person] = []

    async def person(org_id: uuid.UUID, role: str) -> Person:
        p = Person(user_id=uuid.uuid4(), sub=f'files-{uuid.uuid4().hex[:12]}')
        await sql(
            'insert into taas_user_account (id, email, username, email_verified, joined_at, login_count, is_root_account, '
            'failed_reset_attempts, mfa_enabled, created_at, updated_at, tenant_id, directory_id) values (:id, :email, '
            ':email, true, current_date, 0, false, 0, false, now(), now(), :t, :sub)',
            {
                'id': p.user_id,
                'email': f'{p.sub}@example.test',
                't': test_org.tenant_id,
                'sub': p.sub,
            },
        )
        await sql(
            'insert into taas_organization_members (id, user_id, organization_id, tenant_id, role, is_owner, created_at, '
            "updated_at, joined_via) values (:id, :u, :o, :t, :r, false, now(), now(), 'admin')",
            {
                'id': uuid.uuid4(),
                'u': p.user_id,
                'o': org_id,
                't': test_org.tenant_id,
                'r': role,
            },
        )
        await grant(
            p.user_id, role, f'org:{org_id}'
        )  # the IAM grants it with the membership
        persons.append(p)
        return p

    sibling = uuid.uuid7()
    await sql(
        'insert into taas_organizations (id, name, status, slug, created_at, updated_at, tenant_id, parent_id, path, depth) '
        "values (:id, 'Sibling', 'ACTIVE', :slug, now(), now(), :t, :parent, :path, 1)",
        {
            'id': sibling,
            'slug': f'{test_org.slug}-sib',
            't': test_org.tenant_id,
            'parent': test_org.organization_id,
            'path': f'/{test_org.organization_id}/{sibling}/',
        },
    )
    out = People(
        admin=await person(test_org.organization_id, 'org_admin'),
        member=await person(test_org.organization_id, 'org_member'),
        child=await person(test_org.child_organization_id, 'org_member'),
        sibling_org=sibling,
    )
    yield out
    ids = [str(p.user_id) for p in persons]
    await sql(
        "delete from taas_casbin_rule where ptype = 'g' and v0 = any(:ids)",
        {'ids': ids},
    )
    await sql(
        'delete from taas_organization_members where user_id = any(:ids)',
        {'ids': [p.user_id for p in persons]},
    )
    await sql(
        'delete from taas_user_account where id = any(:ids)',
        {'ids': [p.user_id for p in persons]},
    )


@pytest.fixture
async def iam(app, test_org) -> AsyncIterator[None]:
    from ews.security import (
        EwsAuthSettings,
        SessionVerifierT,
        VerifiedSession,
        configure_security,
    )

    class Verifier(SessionVerifierT):
        async def verify(self, headers):
            auth = headers.get('authorization', '')
            return VerifiedSession(sub=auth.split()[1]) if auth else None

    configure_security(settings=EwsAuthSettings(mode='iam'), verifier=Verifier())
    yield
    configure_security(
        settings=EwsAuthSettings(
            mode='dev', dev_organization_id=str(test_org.organization_id)
        )
    )


def _as(app, person: Person, org_id: uuid.UUID) -> httpx.AsyncClient:
    headers = {
        'Authorization': f'Bearer {person.sub}',
        'X-Organization-Id': str(org_id),
        'Origin': 'http://testserver',
    }
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url='http://testserver',
        headers=headers,
    )


async def test_file_0200_0206_permission_matrix(app, test_org, people: People, iam):
    from ews.authz import grant, revoke_domain

    root, child_org = test_org.organization_id, test_org.child_organization_id
    async with (
        _as(app, people.admin, root) as admin,
        _as(app, people.member, root) as member,
        _as(app, people.member, child_org) as member_in_child,
        _as(app, people.child, child_org) as child,
        _as(app, people.admin, child_org) as admin_in_child,
    ):
        # Gate: every signed-in member opens the app; only admins create shared drives.
        a = (await admin.get(f'{FILES}/access')).json()
        m = (await member.get(f'{FILES}/access')).json()
        assert (
            a['can_create_shared_drive'] is True
            and m['can_create_shared_drive'] is False
        )
        org_drive = a['organization_drive_id']
        assert (
            m['organization_drive_id'] == org_drive
        )  # implicit role of the organization's members
        assert m['personal_drive_id'] != a['personal_drive_id']
        assert (
            await member.post(f'{FILES}/drives/', json={'name': 'Nope'})
        ).status_code == 403

        # Organization drive, members = Editor (default): upload, trash, restore; no purge, no member changes.
        up = await _upload(member, org_drive, 'member-note.txt')
        assert up.status_code == 201, up.text
        note = up.json()['node']
        assert (await member.delete(f'{FILES}/nodes/{note["id"]}')).status_code == 204
        assert (
            await member.get(f'{FILES}/drives/{org_drive}/trash')
        ).status_code == 200
        assert (
            await member.post(f'{FILES}/nodes/{note["id"]}/restore')
        ).status_code == 200  # editor restore OK
        await member.delete(f'{FILES}/nodes/{note["id"]}')
        assert (
            await member.delete(
                f'{FILES}/nodes/{note["id"]}', params={'permanent': True}
            )
        ).status_code == 403
        assert (
            await member.delete(f'{FILES}/drives/{org_drive}/trash')
        ).status_code == 403
        assert (
            await member.get(f'{FILES}/drives/{org_drive}/members')
        ).status_code == 200
        grant_child = {'user_id': str(people.child.user_id), 'role': 'drive_viewer'}
        assert (
            await member.put(f'{FILES}/drives/{org_drive}/members', json=grant_child)
        ).status_code == 403
        assert (
            await member.patch(
                f'{FILES}/drives/{org_drive}',
                json={'default_member_role': 'drive_viewer'},
            )
        ).status_code == 403
        assert (
            await admin.delete(
                f'{FILES}/nodes/{note["id"]}', params={'permanent': True}
            )
        ).status_code == 204

        # The organization switches its members to Viewer: read and download, no upload (viewer 403).
        res = await admin.patch(
            f'{FILES}/drives/{org_drive}', json={'default_member_role': 'drive_viewer'}
        )
        assert (
            res.status_code == 200
            and res.json()['default_member_role'] == 'drive_viewer'
        )
        admin_file = (
            await _upload(admin, org_drive, 'policy.pdf', b'%PDF', 'application/pdf')
        ).json()['node']
        assert (await _upload(member, org_drive, 'viewer.txt')).status_code == 403
        assert (
            await member.get(f'{FILES}/nodes/{admin_file["id"]}/download')
        ).status_code == 200
        assert (
            await member.patch(
                f'{FILES}/nodes/{admin_file["id"]}', json={'name': 'x.pdf'}
            )
        ).status_code == 403
        assert (
            await member.get(f'{FILES}/drives/{org_drive}/trash')
        ).status_code == 403
        drive = next(
            d
            for d in (await member.get(f'{FILES}/drives/')).json()
            if d['id'] == org_drive
        )
        assert (
            drive['role'] == 'drive_viewer'
            and 'files.item:create' not in drive['permissions']
        )
        await admin.patch(
            f'{FILES}/drives/{org_drive}', json={'default_member_role': 'drive_editor'}
        )

        # Shared drive: explicit members only (404 for the others, also in lists and search).
        shared = (await admin.post(f'{FILES}/drives/', json={'name': 'Board'})).json()
        assert shared['role'] == 'drive_manager'
        secret = (await _upload(admin, shared['id'], 'board-minutes-xyz.txt')).json()[
            'node'
        ]
        assert (await member.get(f'{FILES}/drives/{shared["id"]}')).status_code == 404
        assert (await member.get(f'{FILES}/nodes/{secret["id"]}')).status_code == 404
        assert (
            await member.get(f'{FILES}/nodes/{secret["id"]}/download')
        ).status_code == 404
        assert shared['id'] not in [
            d['id'] for d in (await member.get(f'{FILES}/drives/')).json()
        ]
        assert (
            await member.get(f'{FILES}/search', params={'q': 'board-minutes-xyz'})
        ).json()['total'] == 0
        assert (
            await member.get(f'{FILES}/search', params={'drive_id': shared['id']})
        ).status_code == 404

        add = await admin.put(
            f'{FILES}/drives/{shared["id"]}/members',
            json={'user_id': str(people.member.user_id), 'role': 'drive_viewer'},
        )
        assert add.status_code == 200, add.text
        assert (
            await member.get(f'{FILES}/search', params={'q': 'board-minutes-xyz'})
        ).json()['total'] == 1
        assert (await _upload(member, shared['id'], 'viewer.txt')).status_code == 403
        await admin.put(
            f'{FILES}/drives/{shared["id"]}/members',
            json={'user_id': str(people.member.user_id), 'role': 'drive_editor'},
        )
        mine = (await _upload(member, shared['id'], 'editor.txt')).json()['node']
        assert (await member.delete(f'{FILES}/nodes/{mine["id"]}')).status_code == 204
        assert (
            await member.post(f'{FILES}/nodes/{mine["id"]}/restore')
        ).status_code == 200
        assert (
            await member.put(f'{FILES}/drives/{shared["id"]}/members', json=grant_child)
        ).status_code == 403
        assert (
            await member.delete(f'{FILES}/drives/{shared["id"]}')
        ).status_code == 403

        # A Drive Manager (not an admin) manages members: manager-only member changes.
        await admin.put(
            f'{FILES}/drives/{shared["id"]}/members',
            json={'user_id': str(people.member.user_id), 'role': 'drive_manager'},
        )
        res = await member.put(
            f'{FILES}/drives/{shared["id"]}/members', json=grant_child
        )
        assert res.status_code == 200, res.text
        members = {
            x['user_id']: x
            for x in (await member.get(f'{FILES}/drives/{shared["id"]}/members')).json()
        }
        assert members[str(people.child.user_id)]['role'] == 'drive_viewer'
        assert (
            members[str(people.admin.user_id)].get('inherited') is not True
        )  # creator = drive_manager
        assert (
            await member.delete(
                f'{FILES}/drives/{shared["id"]}/members/{people.child.user_id}'
            )
        ).status_code == 204
        assert (
            await admin.delete(
                f'{FILES}/drives/{shared["id"]}/members/{people.member.user_id}'
            )
        ).status_code == 204
        assert (await member.get(f'{FILES}/drives/{shared["id"]}')).status_code == 404
        activity = {
            x['action']
            for x in (await admin.get(f'{FILES}/drives/{shared["id"]}/activity')).json()
        }
        assert {'drive.created', 'member.granted', 'member.revoked'} <= activity

        # Parent-organization member in the child organization: no implicit role there → 404.
        child_drive = (await child.get(f'{FILES}/access')).json()[
            'organization_drive_id'
        ]
        assert child_drive and child_drive != org_drive
        assert (await _upload(child, child_drive, 'child.txt')).status_code == 201
        assert (await member_in_child.get(f'{FILES}/access')).json().get(
            'organization_drive_id'
        ) is None
        assert (
            await member_in_child.get(f'{FILES}/drives/{child_drive}')
        ).status_code == 404
        assert (
            await member_in_child.get(f'{FILES}/drives/{child_drive}/nodes')
        ).status_code == 404
        # Another organization's drive (the root's, from the child) → 404.
        assert (await child.get(f'{FILES}/drives/{org_drive}')).status_code == 404
        assert (await child.get(f'{FILES}/nodes/{admin_file["id"]}')).status_code == 404
        # Admin of an ancestor organization = Manager (oversight), audited (File-0200).
        assert (
            await admin_in_child.get(f'{FILES}/drives/{child_drive}')
        ).status_code == 200
        audit = (
            await admin_in_child.get(f'{FILES}/drives/{child_drive}/activity')
        ).json()
        assert any(
            x['action'] == 'admin.access' and x['detail']['via'] == 'ancestor'
            for x in audit
        )

        # Sibling organization drive: foreign for the members of the root and the child organization.
        async with _as(app, people.admin, people.sibling_org) as admin_in_sibling:
            sibling_drive = (await admin_in_sibling.get(f'{FILES}/access')).json()[
                'organization_drive_id'
            ]
        assert (await member.get(f'{FILES}/drives/{sibling_drive}')).status_code == 404
        assert (
            await child.get(f'{FILES}/drives/{sibling_drive}/nodes')
        ).status_code == 404

        # My files is private: organization admins do not see it (404); tenant admins do, audited (File-0201).
        personal = m['personal_drive_id']
        private = (await _upload(member, personal, 'private.txt')).json()['node']
        assert (await admin.get(f'{FILES}/drives/{personal}')).status_code == 404
        assert (await admin.get(f'{FILES}/nodes/{private["id"]}')).status_code == 404
        assert personal not in [
            d['id'] for d in (await admin.get(f'{FILES}/drives/')).json()
        ]
        await grant(
            people.admin.user_id, 'tenant_admin', f'tenant:{test_org.tenant_id}'
        )
        try:
            assert (await admin.get(f'{FILES}/drives/{personal}')).status_code == 200
            assert (
                await admin.get(f'{FILES}/nodes/{private["id"]}/download')
            ).status_code == 200
            audit = (await member.get(f'{FILES}/drives/{personal}/activity')).json()
            assert any(
                x['action'] == 'admin.access' and x['detail']['via'] == 'tenant'
                for x in audit
            )
        finally:
            await revoke_domain(
                f'tenant:{test_org.tenant_id}', user_id=people.admin.user_id
            )

        # Signed out → 401; foreign tenant header → 404.
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url='http://testserver'
        ) as anon:
            assert (await anon.get(f'{FILES}/access')).status_code == 401
        assert (
            await member.get(
                f'{FILES}/drives/', headers={'X-Organization-Id': str(uuid.uuid4())}
            )
        ).status_code == 404
