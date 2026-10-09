"""``/api/v1/knowledge`` end to end on the local database (taas-specs/knowledge/knowledge-app-spec.md): K1 spaces &
access, K2 pages & editor. Development sign-in unless a test switches to ``iam`` (permission matrix)."""

from __future__ import annotations

import base64
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
import pytest

KB = '/api/v1/knowledge'


@pytest.fixture(scope='module', autouse=True)
def kb_storage(test_org):
    """Attachments go to an in-memory private storage behind the storage resolver (``ews.shared.use_storage``); the
    previous resolver is restored afterwards (other modules swap it too)."""
    from blob_service import (
        MemoryBlobAdapter,
        MemoryTenantBucketRegistry,
        create_blob_service,
        create_storage_resolver,
    )
    from ews.shared import storage_resolver, use_storage
    from foundation.blob import StorageSettings

    try:
        previous = storage_resolver()
    except Exception:  # noqa: BLE001 — nothing registered
        previous = None
    registry = MemoryTenantBucketRegistry({str(test_org.tenant_id): '12345678'})
    blob = create_blob_service(
        adapter=MemoryBlobAdapter(), registry=registry, register=False
    )
    settings = StorageSettings(
        STORAGE_PRIVATE_MODE='pooled', STORAGE_PRIVATE_BUCKET='taas-private-kb-test'
    )
    use_storage(create_storage_resolver(blob, registry, settings, register=False))
    yield
    use_storage(previous)


def _doc(text: str) -> dict:
    return {
        'schemaVersion': 1,
        'sections': [
            {'id': 'h', 'type': 'heading', 'props': {'text': text, 'level': 2}},
            {
                'id': 'body',
                'type': 'richText',
                'content': {
                    'type': 'doc',
                    'content': [
                        {
                            'type': 'paragraph',
                            'content': [{'type': 'text', 'text': text}],
                        }
                    ],
                },
            },
        ],
    }


def _word() -> str:
    return f'kbword{uuid.uuid4().hex[:10]}'


async def _space(client: httpx.AsyncClient, **extra) -> dict:
    res = await client.post(
        f'{KB}/spaces', json={'name': f'Space {uuid.uuid4().hex[:6]}', **extra}
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _page(client: httpx.AsyncClient, space_id: str, **extra) -> dict:
    res = await client.post(f'{KB}/spaces/{space_id}/pages', json=extra)
    assert res.status_code == 201, res.text
    return res.json()


async def _published(
    client: httpx.AsyncClient, space_id: str, text: str, **extra
) -> dict:
    page = await _page(
        client, space_id, title=extra.pop('title', text[:40]), doc=_doc(text), **extra
    )
    res = await client.post(f'{KB}/pages/{page["id"]}/publish', json={})
    assert res.status_code == 200, res.text
    return res.json()


def _dev_client(app, test_org, email: str) -> httpx.AsyncClient:
    cookie = (
        base64.urlsafe_b64encode(json.dumps({'email': email, 'name': email}).encode())
        .rstrip(b'=')
        .decode()
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url='http://testserver',
        cookies={'taas_dev_session': cookie},
        headers={
            'X-Organization-Id': str(test_org.organization_id),
            'Origin': 'http://testserver',
        },
    )


# --- development mode: flows ------------------------------------------------------------------------


async def test_kb0101_spaces_crud_and_directory(client: httpx.AsyncClient, test_org):
    access = (await client.get(f'{KB}/access')).json()
    assert access == {
        'allowed': True,
        'can_create_space': True,
        'organization_slug': test_org.slug,
    }
    assert [r['key'] for r in (await client.get(f'{KB}/roles')).json()] == [
        'kb_space_admin',
        'kb_space_editor',
        'kb_space_viewer',
    ]

    space = await _space(
        client, name='HR Policies', visibility='tenant', icon='shield', color='#AA00ff'
    )
    assert (
        space['slug'].startswith('hr-policies')
        and space['visibility'] == 'tenant'
        and space['color'] == '#aa00ff'
    )
    assert (
        space['organization_id'] == str(test_org.organization_id)
        and 'kb.page:publish' in space['permissions']
    )
    taken = await client.post(
        f'{KB}/spaces', json={'name': 'Again', 'slug': space['slug']}
    )
    assert taken.status_code == 409 and taken.json()['extra']['code'] == 'slug_taken'
    assert (
        await client.post(f'{KB}/spaces', json={'name': 'Bad', 'color': 'red'})
    ).status_code == 400
    assert (await client.post(f'{KB}/spaces', json={'name': ' '})).status_code == 400

    assert space['id'] in [s['id'] for s in (await client.get(f'{KB}/spaces')).json()]
    updated = await client.patch(
        f'{KB}/spaces/{space["id"]}',
        json={
            'name': 'HR',
            'visibility': 'organization',
            'include_sub_orgs': True,
            'icon': None,
        },
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert (
        body['name'] == 'HR'
        and body['include_sub_orgs'] is True
        and body.get('icon') is None
    )
    restricted = await client.patch(
        f'{KB}/spaces/{space["id"]}', json={'visibility': 'restricted'}
    )
    assert restricted.json()['include_sub_orgs'] is False

    assert (await client.get(f'{KB}/spaces/not-a-uuid')).status_code == 404
    assert (await client.get(f'{KB}/spaces/{uuid.uuid4()}')).status_code == 404
    assert (await client.delete(f'{KB}/spaces/{space["id"]}')).status_code == 204
    assert (await client.get(f'{KB}/spaces/{space["id"]}')).status_code == 404
    assert space['id'] not in [
        s['id'] for s in (await client.get(f'{KB}/spaces')).json()
    ]


async def test_kb0300_page_tree_move_depth_and_soft_delete(client: httpx.AsyncClient):
    space = await _space(client)
    sid = space['id']
    root = await _page(client, sid, title='Root')
    child = await _page(client, sid, title='Child', parent_id=root['id'])
    grandchild = await _page(client, sid, title='Grandchild', parent_id=child['id'])
    first = await _page(client, sid, title='First', position=0)
    tree = (await client.get(f'{KB}/spaces/{sid}/pages')).json()
    tops = [p['title'] for p in tree if p['parent_id'] is None]
    assert (
        tops == ['First', 'Root']
        and grandchild['depth'] == 2
        and child['status'] == 'draft'
    )

    # Move "Child" (and its sub-page) to the top level, first position; into its own subtree → 400.
    moved = await client.post(
        f'{KB}/pages/{child["id"]}/move', json={'parent_id': None, 'position': 0}
    )
    assert moved.status_code == 200 and moved.json()['depth'] == 0
    assert (await client.get(f'{KB}/pages/{grandchild["id"]}')).json()['depth'] == 1
    assert (
        await client.post(
            f'{KB}/pages/{child["id"]}/move', json={'parent_id': grandchild['id']}
        )
    ).status_code == 400
    tops = [
        p['title']
        for p in (await client.get(f'{KB}/spaces/{sid}/pages')).json()
        if p['parent_id'] is None
    ]
    assert tops == ['Child', 'First', 'Root']

    # ≤ 10 levels: a chain of 10 accepts no 11th level, and no move that would make it deeper.
    chain = [first]
    for i in range(9):
        chain.append(
            await _page(client, sid, title=f'L{i + 2}', parent_id=chain[-1]['id'])
        )
    assert chain[-1]['depth'] == 9
    assert (
        await client.post(
            f'{KB}/spaces/{sid}/pages',
            json={'title': 'L11', 'parent_id': chain[-1]['id']},
        )
    ).status_code == 400
    assert (
        await client.post(
            f'{KB}/pages/{child["id"]}/move', json={'parent_id': chain[-2]['id']}
        )
    ).status_code == 400
    other_space = await _space(client)
    assert (
        await client.post(
            f'{KB}/pages/{child["id"]}/move',
            json={'parent_id': (await _page(client, other_space['id']))['id']},
        )
    ).status_code == 400

    # Delete = soft delete of the subtree.
    assert (await client.delete(f'{KB}/pages/{child["id"]}')).status_code == 204
    assert (await client.get(f'{KB}/pages/{grandchild["id"]}')).status_code == 404
    from foundation.db.advanced_db_manager import MainDatabase
    from sqlalchemy import text

    async with MainDatabase.get_instance().get_engine().connect() as conn:
        rows = (
            await conn.execute(
                text('select deleted_at from taas_kb_pages where id = any(:ids)'),
                {'ids': [uuid.UUID(child['id']), uuid.UUID(grandchild['id'])]},
            )
        ).all()
    assert len(rows) == 2 and all(r.deleted_at is not None for r in rows)


async def test_kb0302_drafts_publish_versions_and_restore(client: httpx.AsyncClient):
    space = await _space(client)
    page = await _page(client, space['id'], template='sop')
    pid = page['id']
    assert page['title'] == 'Standard operating procedure' and page['status'] == 'draft'
    detail = (await client.get(f'{KB}/pages/{pid}')).json()
    assert (
        detail['view'] == 'draft'
        and detail['doc']['sections']
        and detail['space']['id'] == space['id']
    )
    draft_id = detail['draft_revision_id']

    bad = await client.put(
        f'{KB}/pages/{pid}/draft',
        json={'doc': {'schemaVersion': 1, 'sections': [{'id': 'x', 'type': 'nope'}]}},
    )
    assert bad.status_code == 400 and bad.json()['extra']['issues']
    assert (await client.put(f'{KB}/pages/{pid}/draft', json={})).status_code == 400
    saved = (
        await client.put(
            f'{KB}/pages/{pid}/draft',
            json={
                'title': 'Onboarding',
                'doc': _doc('v1 text'),
                'base_revision_id': draft_id,
            },
        )
    ).json()
    assert (
        saved['revision_id'] == draft_id and saved['title'] == 'Onboarding'
    )  # autosave in place

    published = await client.post(f'{KB}/pages/{pid}/publish', json={'note': 'First'})
    assert published.status_code == 200 and published.json()['status'] == 'published'
    again = await client.post(f'{KB}/pages/{pid}/publish', json={})
    assert again.status_code == 409 and again.json()['extra']['code'] == 'no_changes'

    second = (
        await client.put(
            f'{KB}/pages/{pid}/draft',
            json={'doc': _doc('v2 text'), 'title': 'Onboarding v2'},
        )
    ).json()
    assert second['revision_id'] != draft_id and second['status'] == 'changed'
    live = (await client.get(f'{KB}/pages/{pid}', params={'view': 'published'})).json()
    assert (
        live['view'] == 'published'
        and live['title'] == 'Onboarding'
        and live['version'] == 1
    )
    assert 'v1 text' in json.dumps(live['doc'])
    assert (await client.post(f'{KB}/pages/{pid}/publish', json={})).status_code == 200

    revisions = (await client.get(f'{KB}/pages/{pid}/revisions')).json()
    assert (
        [r['version'] for r in revisions] == [2, 1]
        and revisions[0]['is_published']
        and revisions[1]['note'] == 'First'
    )
    v1 = (await client.get(f'{KB}/pages/{pid}/revisions/{revisions[1]["id"]}')).json()
    assert 'v1 text' in json.dumps(v1['doc'])
    restored = await client.post(
        f'{KB}/pages/{pid}/revisions/{revisions[1]["id"]}/restore'
    )
    assert (
        restored.status_code == 200
        and restored.json()['status'] == 'changed'
        and restored.json()['title'] == 'Onboarding'
    )
    after = (await client.get(f'{KB}/pages/{pid}/revisions')).json()
    assert (
        after[0]['source'] == 'restore'
        and after[0]['is_draft']
        and after[0]['note'] == 'Restored from version 1'
    )
    assert (
        await client.get(f'{KB}/pages/{pid}/revisions/{uuid.uuid4()}')
    ).status_code == 404


async def test_kb0302_discard_draft_goes_back_to_the_published_version(
    client: httpx.AsyncClient,
):
    """Draft mode: unpublished changes can be thrown away; the discarded draft stays in the history."""
    space = await _space(client)
    pid = (await _page(client, space['id']))['id']
    never = await client.post(f'{KB}/pages/{pid}/draft/discard')
    assert never.status_code == 409 and never.json()['extra']['code'] == 'never_published'
    await client.put(f'{KB}/pages/{pid}/draft', json={'title': 'Live', 'doc': _doc('live text')})
    assert (await client.post(f'{KB}/pages/{pid}/publish', json={})).status_code == 200
    nothing = await client.post(f'{KB}/pages/{pid}/draft/discard')
    assert nothing.status_code == 409 and nothing.json()['extra']['code'] == 'no_changes'

    await client.put(f'{KB}/pages/{pid}/draft', json={'title': 'Edited', 'doc': _doc('unwanted text')})
    assert (await client.get(f'{KB}/pages/{pid}')).json()['status'] == 'changed'
    discarded = await client.post(f'{KB}/pages/{pid}/draft/discard')
    assert discarded.status_code == 200, discarded.text
    assert discarded.json()['status'] == 'published' and discarded.json()['title'] == 'Live'
    draft = (await client.get(f'{KB}/pages/{pid}')).json()
    assert draft['title'] == 'Live' and 'live text' in json.dumps(draft['doc'])
    assert 'unwanted text' not in json.dumps(draft['doc'])
    history = (await client.get(f'{KB}/pages/{pid}/revisions')).json()
    assert any(r['title'] == 'Edited' and not r.get('is_draft') for r in history)  # still restorable
    # the next edit starts a new draft, the published version stays untouched
    await client.put(f'{KB}/pages/{pid}/draft', json={'doc': _doc('new try')})
    live = (await client.get(f'{KB}/pages/{pid}', params={'view': 'published'})).json()
    assert 'live text' in json.dumps(live['doc'])


async def test_kb0302_soft_lock_and_stale_draft(
    app, client: httpx.AsyncClient, test_org
):
    space = await _space(client)
    page = await _page(client, space['id'], title='Locked page')
    base = f'{KB}/pages/{page["id"]}'
    lock = (await client.post(f'{base}/lock', json={})).json()
    assert lock['locked'] is True and lock['holder_id'] == str(test_org.user_id)
    async with _dev_client(
        app, test_org, f'kb-other-{uuid.uuid4().hex[:6]}@example.test'
    ) as other:
        theirs = (await other.post(f'{base}/lock', json={})).json()
        assert theirs['locked'] is False and theirs['holder_id'] == str(
            test_org.user_id
        )
        shown = (await other.get(base)).json()['lock']
        assert shown['locked'] is False and shown['holder_id'] == str(test_org.user_id)
        blocked = await other.put(f'{base}/draft', json={'title': 'Mine'})
        assert (
            blocked.status_code == 409 and blocked.json()['extra']['code'] == 'locked'
        )
        assert (await other.post(f'{base}/publish', json={})).status_code == 409
        # Take over after confirmation; the first editor is now blocked, then its stale draft is refused.
        assert (await other.post(f'{base}/lock', json={'force': True})).json()[
            'locked'
        ] is True
        assert (
            await client.put(f'{base}/draft', json={'title': 'Back'})
        ).status_code == 409
        draft_id = (await client.get(base)).json()['draft_revision_id']
        theirs = (
            await other.put(
                f'{base}/draft', json={'title': 'Theirs', 'base_revision_id': draft_id}
            )
        ).json()
        assert (
            theirs['revision_id'] != draft_id
        )  # another author → a new draft revision
        assert (await other.delete(f'{base}/lock')).status_code == 204
    stale = await client.put(
        f'{base}/draft', json={'title': 'Mine again', 'base_revision_id': draft_id}
    )
    assert stale.status_code == 409 and stale.json()['extra']['code'] == 'stale_draft'
    assert (
        await client.put(
            f'{base}/draft',
            json={'title': 'Mine again', 'base_revision_id': theirs['revision_id']},
        )
    ).status_code == 200


async def test_kb0303_owner_review_interval_and_verification(
    client: httpx.AsyncClient, test_org, sql
):
    space = await _space(client)
    draft = await _page(client, space['id'], title='Draft only')
    assert (await client.post(f'{KB}/pages/{draft["id"]}/verify')).status_code == 400
    page = await _published(client, space['id'], f'review me {_word()}')
    pid = page['id']
    assert (
        page['owner_id'] == str(test_org.user_id)
        and page['review_interval_days'] == 180
    )
    assert page['review_status'] == 'verified' and page['verified_until']

    due = (
        await client.patch(f'{KB}/pages/{pid}', json={'review_interval_days': 10})
    ).json()
    assert due['review_status'] == 'due'
    assert pid in [p['id'] for p in (await client.get(f'{KB}/review')).json()]
    await sql(
        'update taas_kb_pages set verified_until = :t where id = :id',
        {'t': datetime.now(UTC) - timedelta(days=1), 'id': uuid.UUID(pid)},
    )
    assert (await client.get(f'{KB}/pages/{pid}')).json()['review_status'] == 'expired'
    await client.patch(f'{KB}/pages/{pid}', json={'review_interval_days': 90})
    verified = (await client.post(f'{KB}/pages/{pid}/verify')).json()
    assert verified['review_status'] == 'verified'
    assert pid not in [p['id'] for p in (await client.get(f'{KB}/review')).json()]
    no_review = (
        await client.patch(f'{KB}/pages/{pid}', json={'review_interval_days': None})
    ).json()
    assert (
        no_review.get('verified_until') is None
        and no_review['review_status'] == 'verified'
    )

    assert (
        await client.patch(f'{KB}/pages/{pid}', json={'owner_id': str(uuid.uuid4())})
    ).status_code == 400
    assert (
        await client.patch(f'{KB}/pages/{pid}', json={'review_interval_days': 0})
    ).status_code == 400
    owned = await client.patch(
        f'{KB}/pages/{pid}',
        json={'owner_id': str(test_org.user_id), 'slug': 'reviewed'},
    )
    assert owned.status_code == 200 and owned.json()['slug'] == 'reviewed'
    clash = await client.patch(f'{KB}/pages/{draft["id"]}', json={'slug': 'reviewed'})
    assert clash.status_code == 409


async def test_kb0305_private_attachments_through_signed_urls(
    client: httpx.AsyncClient, sql
):
    space = await _space(client)
    page = await _published(client, space['id'], 'with files')
    base = f'{KB}/pages/{page["id"]}/attachments'
    up = await client.post(
        base, files={'file': ('Q3 report.txt', b'quarterly numbers', 'text/plain')}
    )
    assert up.status_code == 201, up.text
    att = up.json()
    assert (
        att['filename'] == 'Q3 report.txt'
        and att['mime'] == 'text/plain'
        and att['size'] == 17
    )
    assert (
        await client.post(base, files={'file': ('empty.txt', b'', 'text/plain')})
    ).status_code == 400
    assert [a['id'] for a in (await client.get(base)).json()] == [att['id']]

    from foundation.db.advanced_db_manager import MainDatabase
    from sqlalchemy import text

    async with MainDatabase.get_instance().get_engine().connect() as conn:
        key = (
            await conn.execute(
                text('select key from taas_kb_attachments where id = :id'),
                {'id': uuid.UUID(att['id'])},
            )
        ).scalar_one()
    assert key.startswith(f'knowledge/{space["id"]}/{att["id"]}/1/original')

    link = (await client.get(f'{base}/{att["id"]}/download')).json()
    assert (
        '/api/v1/knowledge/files/' in link['url']
        and link['filename'] == 'Q3 report.txt'
    )
    path = link['url'].split('http://testserver', 1)[-1]
    async with httpx.AsyncClient(
        transport=client._transport, base_url='http://testserver'
    ) as anon:  # no session
        res = await anon.get(path)
        assert res.status_code == 200 and res.content == b'quarterly numbers'
        assert (
            res.headers['content-disposition'].startswith('attachment;')
            and res.headers['x-content-type-options'] == 'nosniff'
        )
        inline = (
            await client.get(f'{base}/{att["id"]}/download', params={'inline': 'true'})
        ).json()
        shown = await anon.get(inline['url'].split('http://testserver', 1)[-1])
        assert shown.status_code == 200 and 'content-disposition' not in shown.headers
        assert (await anon.get(path[:-3] + 'abc')).status_code == 404

    assert (await client.delete(f'{base}/{att["id"]}')).status_code == 204
    assert (await client.get(base)).json() == []
    assert (await client.get(f'{base}/{att["id"]}/download')).status_code == 404


async def test_kb0104_home_search_and_templates(client: httpx.AsyncClient):
    templates = (await client.get(f'{KB}/templates')).json()
    assert [t['key'] for t in templates] == [
        'sop',
        'policy',
        'how-to',
        'faq',
        'meeting-notes',
        'decision-record',
    ]
    valid = await client.post(f'{KB}/validate', json={'doc': templates[0]['doc']})
    assert valid.json() == {'valid': True, 'issues': []}
    invalid = await client.post(f'{KB}/validate', json={'doc': {'schemaVersion': 1, 'sections': 'x'}})
    assert invalid.json()['valid'] is False
    space = await _space(client, visibility='tenant')
    word, hidden = _word(), _word()
    page = await _published(
        client,
        space['id'],
        f'Travel expenses {word} are refunded monthly.',
        title='Expenses',
    )
    await _page(client, space['id'], title=f'Draft {hidden}', doc=_doc(hidden))
    hits = (await client.get(f'{KB}/search', params={'q': f'{word} travel'})).json()
    assert (
        [h['id'] for h in hits] == [page['id']]
        and word in hits[0]['snippet']
        and hits[0]['space_name'] == space['name']
    )
    assert (
        await client.get(f'{KB}/search', params={'q': hidden})
    ).json() == []  # drafts are not searchable
    assert (await client.get(f'{KB}/search', params={'q': '  '})).json() == []
    assert (
        await client.get(
            f'{KB}/search', params={'q': word, 'space_id': str(uuid.uuid4())}
        )
    ).json() == []
    home = (await client.get(f'{KB}/home')).json()
    assert page['id'] in [p['id'] for p in home['recent']]
    assert space['id'] in [s['id'] for s in (await client.get(f'{KB}/spaces')).json()]
    assert isinstance(home['spaces'], list) and isinstance(home['review'], list)


# --- IAM mode: permission matrix (Kb-0100…0104) ----------------------------------------------------------


@dataclass(frozen=True)
class Person:
    id: uuid.UUID
    sub: str
    email: str
    org_slug: str


async def _execute(statement: str, params: dict | None = None) -> None:
    from foundation.db.advanced_db_manager import MainDatabase
    from sqlalchemy import text

    async with MainDatabase.get_instance().get_engine().begin() as conn:
        await conn.execute(text(statement), params or {})


_INSERT_ORG = (
    'insert into taas_organizations (id, name, status, slug, created_at, updated_at, tenant_id, parent_id, path, depth) '
    "values (:id, :name, 'ACTIVE', :slug, now(), now(), :t, :parent, :path, :depth)"
)


async def _person(
    tenant_id: uuid.UUID, org_id: uuid.UUID, org_slug: str, role: str, label: str
) -> Person:
    from ews.authz import grant

    suffix = uuid.uuid4().hex[:8]
    person = Person(
        id=uuid.uuid4(),
        sub=f'kb-{label}-{suffix}',
        email=f'kb-{label}-{suffix}@example.test',
        org_slug=org_slug,
    )
    await _execute(
        'insert into taas_user_account (id, email, username, name, email_verified, joined_at, login_count, is_root_account, '
        'failed_reset_attempts, mfa_enabled, created_at, updated_at, tenant_id, directory_id) values (:id, :email, :email, '
        ':name, true, current_date, 0, false, 0, false, now(), now(), :t, :sub)',
        {
            'id': person.id,
            'email': person.email,
            'name': label.title(),
            't': tenant_id,
            'sub': person.sub,
        },
    )
    await _execute(
        'insert into taas_organization_members (id, user_id, organization_id, tenant_id, role, is_owner, created_at, '
        "updated_at, joined_via) values (:id, :u, :o, :t, :role, false, now(), now(), 'admin')",
        {'id': uuid.uuid4(), 'u': person.id, 'o': org_id, 't': tenant_id, 'role': role},
    )
    await grant(person.id, role, f'org:{org_id}')
    return person


@dataclass(frozen=True)
class People:
    alice: Person  # org_admin of the root organization
    bob: Person  # org_member of the root organization
    erin: Person  # org_member of the root organization (made a space member)
    carol: Person  # org_member of the child organization
    dave: Person  # org_member of a second sub-organization (sibling of the child)
    eve: Person  # another tenant


@pytest.fixture
async def people(test_org) -> AsyncIterator[People]:
    sibling, foreign_tenant, foreign_org = uuid.uuid7(), uuid.uuid4(), uuid.uuid7()
    suffix = uuid.uuid4().hex[:8]
    root = test_org.organization_id
    await _execute(
        _INSERT_ORG,
        {
            'id': sibling,
            'name': 'KB sibling',
            'slug': f'kb-sib-{suffix}',
            't': test_org.tenant_id,
            'parent': root,
            'path': f'/{root}/{sibling}/',
            'depth': 1,
        },
    )
    await _execute(
        'insert into taas_tenants (id, name, status, slug, created_at, updated_at, tenant_code, account_type) '
        "values (:id, 'KB foreign', 'ACTIVE', :slug, now(), now(), :code, 'organization')",
        {
            'id': foreign_tenant,
            'slug': f'kb-foreign-{suffix}',
            'code': str(uuid.uuid4().int)[:8],
        },
    )
    await _execute(
        _INSERT_ORG,
        {
            'id': foreign_org,
            'name': 'KB foreign',
            'slug': f'kb-foreign-{suffix}',
            't': foreign_tenant,
            'parent': None,
            'path': f'/{foreign_org}/',
            'depth': 0,
        },
    )
    child = test_org.child_organization_id
    crowd = People(
        alice=await _person(
            test_org.tenant_id, root, test_org.slug, 'org_admin', 'alice'
        ),
        bob=await _person(test_org.tenant_id, root, test_org.slug, 'org_member', 'bob'),
        erin=await _person(
            test_org.tenant_id, root, test_org.slug, 'org_member', 'erin'
        ),
        carol=await _person(
            test_org.tenant_id, child, f'{test_org.slug}-child', 'org_member', 'carol'
        ),
        dave=await _person(
            test_org.tenant_id, sibling, f'kb-sib-{suffix}', 'org_member', 'dave'
        ),
        eve=await _person(
            foreign_tenant, foreign_org, f'kb-foreign-{suffix}', 'org_member', 'eve'
        ),
    )
    try:
        yield crowd
    finally:
        ids = [
            p.id
            for p in (
                crowd.alice,
                crowd.bob,
                crowd.erin,
                crowd.carol,
                crowd.dave,
                crowd.eve,
            )
        ]
        await _execute(
            "delete from taas_casbin_rule where ptype = 'g' and v0 = any(:ids)",
            {'ids': [str(i) for i in ids]},
        )
        await _execute(
            'delete from taas_organization_members where user_id = any(:ids)',
            {'ids': ids},
        )
        await _execute(
            'delete from taas_user_account where id = any(:ids)', {'ids': ids}
        )
        await _execute('delete from taas_organizations where id = :id', {'id': sibling})
        await _execute(
            'delete from taas_tenants where id = :id', {'id': foreign_tenant}
        )


@asynccontextmanager
async def _iam_mode(test_org):
    """IAM mode with a verifier that trusts ``Authorization: Bearer <sub>``; back to development mode after."""
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
    try:
        yield
    finally:
        configure_security(
            settings=EwsAuthSettings(
                mode='dev', dev_organization_id=str(test_org.organization_id)
            )
        )


def _as(app, person: Person) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url='http://testserver',
        headers={
            'Authorization': f'Bearer {person.sub}',
            'X-Organization-Slug': person.org_slug,
        },
    )


async def _ids(c: httpx.AsyncClient) -> set[str]:
    res = await c.get(f'{KB}/spaces')
    assert res.status_code == 200, res.text
    return {s['id'] for s in res.json()}


async def test_kb_permission_matrix_in_iam_mode(app, test_org, people: People):
    """Visibility tenant / organization (± sub-organizations) / restricted, implicit viewer read-only, drafts hidden
    from viewers, editors publish, space admins manage members, org_admin creates spaces, org_member cannot,
    kb_admin manages every space, another tenant gets 404 (Kb-0100, Kb-0101, Kb-0103, Kb-0104)."""
    from ews.authz import grant, revoke

    p = people
    async with _iam_mode(test_org):
        async with (
            _as(app, p.alice) as alice,
            _as(app, p.bob) as bob,
            _as(app, p.erin) as erin,
            _as(app, p.carol) as carol,
            _as(app, p.dave) as dave,
            _as(app, p.eve) as eve,
        ):
            # Kb-0101: org_admin creates spaces (and becomes their admin); org_member cannot.
            assert (await alice.get(f'{KB}/access')).json()['can_create_space'] is True
            assert (await bob.get(f'{KB}/access')).json() == {
                'allowed': True,
                'can_create_space': False,
                'organization_slug': test_org.slug,
            }
            assert (
                await bob.post(f'{KB}/spaces', json={'name': 'Nope'})
            ).status_code == 403
            tenant = await _space(alice, name='Handbook', visibility='tenant')
            org = await _space(alice, name='HQ only', visibility='organization')
            subs = await _space(
                alice,
                name='HQ and branches',
                visibility='organization',
                include_sub_orgs=True,
            )
            restricted = await _space(alice, name='Leadership', visibility='restricted')
            child_slug = {
                'X-Organization-Slug': f'{test_org.slug}-child'
            }  # the org admin works in its sub-organization
            res = await alice.post(
                f'{KB}/spaces',
                json={'name': 'Branch', 'visibility': 'organization'},
                headers=child_slug,
            )
            assert res.status_code == 201, res.text
            branch = res.json()
            assert branch['organization_id'] == str(test_org.child_organization_id)
            assert (
                tenant['role'] == 'kb_space_admin'
                and 'kb.space_member:manage' in tenant['permissions']
            )
            word = _word()
            spaces = (tenant, org, subs, restricted, branch)
            pages = {
                s['id']: await _published(alice, s['id'], f'{s["name"]} {word}')
                for s in spaces
            }
            draft = await _page(alice, tenant['id'], title='Unpublished plan')

            # Kb-0100 / Kb-0104: the directory is tenant-wide and trimmed by visibility.
            mine = {s['id'] for s in spaces}
            assert (
                await _ids(alice) & mine == mine
            )  # org_admin of the root: every space of its subtree
            assert await _ids(bob) & mine == {tenant['id'], org['id'], subs['id']}
            assert await _ids(carol) & mine == {tenant['id'], subs['id'], branch['id']}
            assert await _ids(dave) & mine == {tenant['id'], subs['id']}
            assert await _ids(eve) & mine == set()
            assert (await bob.get(f'{KB}/spaces/{restricted["id"]}')).status_code == 404
            assert (await carol.get(f'{KB}/spaces/{org["id"]}')).status_code == 404
            assert (
                await carol.get(f'{KB}/pages/{pages[org["id"]]["id"]}')
            ).status_code == 404
            assert (
                await dave.get(f'{KB}/pages/{pages[tenant["id"]]["id"]}')
            ).status_code == 200
            assert (await eve.get(f'{KB}/spaces/{tenant["id"]}')).status_code == 404
            assert (
                await eve.get(f'{KB}/pages/{pages[tenant["id"]]["id"]}')
            ).status_code == 404
            hits = {
                h['space_id']
                for h in (await carol.get(f'{KB}/search', params={'q': word})).json()
            }
            assert hits == {tenant['id'], subs['id'], branch['id']}
            assert (
                await carol.patch(f'{KB}/spaces/{branch["id"]}', json={'name': 'x'})
            ).status_code == 403
            assert (await eve.get(f'{KB}/search', params={'q': word})).json() == []

            # Implicit viewers read published pages only and cannot edit (Kb-0103).
            viewer_space = (await bob.get(f'{KB}/spaces/{tenant["id"]}')).json()
            assert (
                viewer_space['role'] == 'kb_space_viewer'
                and 'kb.page:update' not in viewer_space['permissions']
            )
            tpage = pages[tenant['id']]['id']
            read = (
                await bob.get(f'{KB}/pages/{tpage}', params={'view': 'draft'})
            ).json()
            assert (
                read['view'] == 'published'
                and read.get('draft_revision_id') is None
                and read.get('lock') is None
            )
            assert (await bob.get(f'{KB}/pages/{draft["id"]}')).status_code == 404
            assert draft['id'] not in [
                x['id']
                for x in (await bob.get(f'{KB}/spaces/{tenant["id"]}/pages')).json()
            ]
            assert draft['id'] in [
                x['id']
                for x in (await alice.get(f'{KB}/spaces/{tenant["id"]}/pages')).json()
            ]
            assert (
                await bob.put(f'{KB}/pages/{tpage}/draft', json={'title': 'x'})
            ).status_code == 403
            assert (
                await bob.post(f'{KB}/pages/{tpage}/publish', json={})
            ).status_code == 403
            assert (await bob.get(f'{KB}/pages/{tpage}/revisions')).status_code == 403
            assert (
                await bob.post(f'{KB}/spaces/{tenant["id"]}/pages', json={'title': 'x'})
            ).status_code == 403
            assert (
                await bob.patch(f'{KB}/spaces/{tenant["id"]}', json={'name': 'x'})
            ).status_code == 403
            assert (
                await bob.get(f'{KB}/spaces/{tenant["id"]}/members')
            ).status_code == 200
            assert (
                await bob.get(f'{KB}/spaces/{tenant["id"]}/member-candidates')
            ).status_code == 403
            assert (
                await bob.post(
                    f'{KB}/pages/{tpage}/attachments',
                    files={'file': ('a.txt', b'a', 'text/plain')},
                )
            ).status_code == 403

            # Space admins manage members of the restricted space; editors publish but do not manage.
            candidates = (
                await alice.get(
                    f'{KB}/spaces/{restricted["id"]}/member-candidates',
                    params={'q': 'kb-erin'},
                )
            ).json()
            assert str(p.erin.id) in [c['user_id'] for c in candidates]
            added = await alice.put(
                f'{KB}/spaces/{restricted["id"]}/members',
                json={'user_id': str(p.erin.id), 'role': 'kb_space_editor'},
            )
            assert added.status_code == 200, added.text
            assert (
                await alice.put(
                    f'{KB}/spaces/{restricted["id"]}/members',
                    json={'user_id': str(p.eve.id), 'role': 'kb_space_viewer'},
                )
            ).status_code == 400
            members = (
                await alice.get(f'{KB}/spaces/{restricted["id"]}/members')
            ).json()
            assert {(m['user_id'], m['role']) for m in members} >= {
                (str(p.alice.id), 'kb_space_admin'),
                (str(p.erin.id), 'kb_space_editor'),
            }
            assert restricted['id'] in await _ids(erin)
            new = await _page(
                erin,
                restricted['id'],
                title='Board minutes',
                doc=_doc(f'minutes {word}'),
            )
            assert (
                await erin.post(f'{KB}/pages/{new["id"]}/publish', json={})
            ).status_code == 200
            assert (
                await erin.post(f'{KB}/pages/{new["id"]}/verify')
            ).status_code == 200
            assert (
                await erin.patch(f'{KB}/spaces/{restricted["id"]}', json={'name': 'x'})
            ).status_code == 403
            assert (
                await erin.put(
                    f'{KB}/spaces/{restricted["id"]}/members',
                    json={'user_id': str(p.bob.id), 'role': 'kb_space_viewer'},
                )
            ).status_code == 403
            assert (
                await erin.delete(f'{KB}/spaces/{restricted["id"]}')
            ).status_code == 403

            # An explicit viewer of the restricted space reads, then loses access when removed.
            await alice.put(
                f'{KB}/spaces/{restricted["id"]}/members',
                json={'user_id': str(p.bob.id), 'role': 'kb_space_viewer'},
            )
            assert (await bob.get(f'{KB}/pages/{new["id"]}')).status_code == 200
            assert (
                await bob.put(f'{KB}/pages/{new["id"]}/draft', json={'title': 'x'})
            ).status_code == 403
            assert (
                await alice.delete(f'{KB}/spaces/{restricted["id"]}/members/{p.bob.id}')
            ).status_code == 204
            assert (await bob.get(f'{KB}/pages/{new["id"]}')).status_code == 404
            assert (
                await alice.delete(f'{KB}/spaces/{restricted["id"]}/members/{p.bob.id}')
            ).status_code == 404

            # Tenant kb_admin manages every space of the tenant, whatever its organization.
            await grant(p.dave.id, 'kb_admin', f'tenant:{test_org.tenant_id}')
            try:
                assert {restricted['id'], branch['id']} <= await _ids(dave)
                assert (
                    await dave.patch(
                        f'{KB}/spaces/{restricted["id"]}', json={'description': 'Board'}
                    )
                ).status_code == 200
                assert (await dave.get(f'{KB}/access')).json()[
                    'can_create_space'
                ] is True
            finally:
                await revoke(p.dave.id, 'kb_admin', f'tenant:{test_org.tenant_id}')
            assert (
                await dave.patch(
                    f'{KB}/spaces/{tenant["id"]}', json={'description': 'x'}
                )
            ).status_code == 403
