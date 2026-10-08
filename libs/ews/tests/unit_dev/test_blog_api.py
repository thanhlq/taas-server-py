"""``/api/v1/blog`` end to end on the local database (taas-specs/blog/blog-app-spec.md, blog-api.md).

Development sign-in (every permission) unless a test switches to ``iam`` mode with real roles: the permission
matrix (admin · editor · author · viewer · organization member without a role · foreign organization).
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from PIL import Image


def _doc(*texts: str) -> dict:
    return {
        'schemaVersion': 1,
        'sections': [
            {
                'id': f'r{i}',
                'type': 'richText',
                'content': {
                    'type': 'doc',
                    'content': [
                        {'type': 'paragraph', 'content': [{'type': 'text', 'text': t}]}
                    ],
                },
            }
            for i, t in enumerate(texts)
        ],
    }


async def _blog(client: httpx.AsyncClient, **extra) -> dict:
    res = await client.post(
        '/api/v1/blog/blogs', json={'name': f'News {uuid.uuid4().hex[:6]}', **extra}
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _post(client: httpx.AsyncClient, blog_id: str, **extra) -> dict:
    res = await client.post(f'/api/v1/blog/blogs/{blog_id}/posts', json=extra)
    assert res.status_code == 201, res.text
    return res.json()


def _png() -> bytes:
    out = io.BytesIO()
    Image.new('RGB', (64, 48), 'teal').save(out, 'PNG')
    return out.getvalue()


# --- blogs ------------------------------------------------------------------------------------------


async def test_access_roles_and_blog_crud(client: httpx.AsyncClient, test_org):
    access = (await client.get('/api/v1/blog/access')).json()
    assert access == {
        'allowed': True,
        'can_create': True,
        'organization_slug': test_org.slug,
    }
    roles = (await client.get('/api/v1/blog/roles')).json()
    assert [r['key'] for r in roles] == [
        'blog_admin',
        'blog_editor',
        'blog_author',
        'blog_viewer',
    ]
    assert [r['key'] for r in roles if r.get('default')] == ['blog_author']

    blog = await _blog(
        client, description='Company news', settings={'posts_per_page': 12}
    )
    assert blog['slug'].startswith('news-') and blog.get('status', 'active') == 'active'
    assert (
        blog['settings']['posts_per_page'] == 12
        and blog['settings']['feed_enabled'] is True
    )
    assert 'blog.post:publish' in blog['permissions']
    assert blog['id'] in [
        b['id'] for b in (await client.get('/api/v1/blog/blogs')).json()
    ]

    # slug unique per organization, shared with the sites of the organization (same public host)
    dup = await client.post(
        '/api/v1/blog/blogs', json={'name': 'Again', 'slug': blog['slug']}
    )
    assert dup.status_code == 409 and dup.json()['extra']['code'] == 'slug_taken'
    site = await client.post(
        '/api/v1/sites/', json={'name': 'Shop', 'slug': f'shop-{uuid.uuid4().hex[:6]}'}
    )
    assert site.status_code == 201, site.text
    clash = await client.post(
        '/api/v1/blog/blogs', json={'name': 'Shop blog', 'slug': site.json()['slug']}
    )
    assert clash.status_code == 409
    assert (
        await client.post(
            '/api/v1/blog/blogs', json={'name': 'Bad', 'slug': 'Bad Slug'}
        )
    ).status_code == 400

    bid = blog['id']
    res = await client.patch(
        f'/api/v1/blog/blogs/{bid}',
        json={'settings': {'feed_full_text': True, 'posts_per_page': None}},
    )
    assert res.status_code == 200, res.text
    assert (
        res.json()['settings']['feed_full_text'] is True
        and res.json()['settings']['posts_per_page'] == 10
    )
    assert (
        await client.patch(
            f'/api/v1/blog/blogs/{bid}', json={'settings': {'unknown': 1}}
        )
    ).status_code == 400
    assert (
        await client.patch(
            f'/api/v1/blog/blogs/{bid}',
            json={'settings': {'default_author_id': str(uuid.uuid4())}},
        )
    ).status_code == 400
    assert (
        await client.patch(f'/api/v1/blog/blogs/{bid}', json={'mount': 'site'})
    ).status_code == 400
    assert (
        await client.patch(f'/api/v1/blog/blogs/{bid}', json={'locale': 'Français'})
    ).status_code == 400

    # archived blog = read-only
    assert (
        await client.patch(f'/api/v1/blog/blogs/{bid}', json={'status': 'archived'})
    ).json()['status'] == 'archived'
    res = await client.post(f'/api/v1/blog/blogs/{bid}/posts', json={'title': 'Nope'})
    assert res.status_code == 409 and res.json()['extra']['code'] == 'blog_archived'
    assert (await client.get(f'/api/v1/blog/blogs/{bid}/posts')).status_code == 200
    await client.patch(f'/api/v1/blog/blogs/{bid}', json={'status': 'active'})

    # soft delete frees the slug; malformed / unknown ids are 404
    assert (await client.delete(f'/api/v1/blog/blogs/{bid}')).status_code == 204
    assert (await client.get(f'/api/v1/blog/blogs/{bid}')).status_code == 404
    assert (
        await client.post(
            '/api/v1/blog/blogs', json={'name': 'Reuse', 'slug': blog['slug']}
        )
    ).status_code == 201
    assert (await client.get('/api/v1/blog/blogs/not-a-uuid')).status_code == 404
    assert (await client.get(f'/api/v1/blog/posts/{uuid.uuid4()}')).status_code == 404

    valid = await client.post('/api/v1/blog/validate', json={'doc': _doc('ok')})
    assert valid.json() == {'valid': True, 'issues': []}
    invalid = await client.post(
        '/api/v1/blog/validate',
        json={'doc': {'schemaVersion': 1, 'sections': [{'id': 'x', 'type': 'nope'}]}},
    )
    assert invalid.json()['valid'] is False and invalid.json()['issues']


# --- posts, drafts, revisions (Blog-0100 / Blog-0101) -------------------------------------------------


async def test_blog_0100_0101_posts_drafts_revisions_lock(
    client: httpx.AsyncClient, test_org
):
    blog = await _blog(client)
    bid = blog['id']
    post = await _post(client, bid)
    pid = post['id']
    assert (
        post['title'] == 'Untitled'
        and post['slug'] == 'untitled'
        and post['status'] == 'draft'
    )
    assert (
        post['doc'] == {'schemaVersion': 1, 'sections': []} and post['can_edit'] is True
    )
    # the creator's author profile is created and credited
    assert [a['user_id'] for a in post['authors']] == [str(test_org.user_id)]
    assert (await _post(client, bid))['slug'] == 'untitled-2'

    # autosave: same user + source within a minute updates the draft revision; a note forces a new one
    body = _doc(' '.join(['word'] * 500))
    first = await client.put(
        f'/api/v1/blog/posts/{pid}/draft', json={'title': 'Hello world', 'doc': body}
    )
    assert first.status_code == 200, first.text
    assert first.json()['word_count'] == 500 and first.json()['reading_minutes'] == 2
    second = (
        await client.put(f'/api/v1/blog/posts/{pid}/draft', json={'doc': _doc('short')})
    ).json()
    assert (
        second['new_revision'] is False
        and second['revision_id'] == first.json()['revision_id']
    )
    named = (
        await client.put(
            f'/api/v1/blog/posts/{pid}/draft',
            json={'doc': _doc('v2 text'), 'note': 'v2'},
        )
    ).json()
    assert named['new_revision'] is True
    md = (
        await client.put(
            f'/api/v1/blog/posts/{pid}/draft',
            json={'doc': _doc('# md'), 'source': 'markdown'},
        )
    ).json()
    assert md['new_revision'] is True
    bad = await client.put(
        f'/api/v1/blog/posts/{pid}/draft',
        json={'doc': {'schemaVersion': 2, 'sections': []}},
    )
    assert bad.status_code == 400 and bad.json()['extra']['issues']

    detail = (await client.get(f'/api/v1/blog/posts/{pid}')).json()
    assert (
        detail['title'] == 'Hello world'
        and detail['doc'] == _doc('# md')
        and detail['revision_source'] == 'markdown'
    )
    # never published + automatic slug: the address follows the title (Blog-0107)
    assert detail['slug'] == 'hello-world' and detail['slug_auto'] is True

    revisions = (await client.get(f'/api/v1/blog/posts/{pid}/revisions')).json()
    assert (
        len(revisions) == 3
        and revisions[0]['is_draft']
        and revisions[0]['created_by_name'] == test_org.email
    )
    oldest = revisions[-1]
    rev = (
        await client.get(f'/api/v1/blog/posts/{pid}/revisions/{oldest["id"]}')
    ).json()
    assert rev['doc'] == _doc('short') and rev['meta']['slug'] == 'hello-world'
    restored = await client.post(
        f'/api/v1/blog/posts/{pid}/revisions/{oldest["id"]}/restore'
    )
    assert restored.status_code == 200 and restored.json()['new_revision'] is True
    detail = (await client.get(f'/api/v1/blog/posts/{pid}')).json()
    assert (
        detail['doc'] == _doc('short')
        and detail['revision_source'] == 'restore'
        and detail['reading_minutes'] == 1
    )
    assert (
        await client.get(f'/api/v1/blog/posts/{pid}/revisions/{uuid.uuid4()}')
    ).status_code == 404

    # soft lock
    lock = (await client.post(f'/api/v1/blog/posts/{pid}/lock', json={})).json()
    assert (
        lock['locked'] is True
        and lock['holder_id'] == str(test_org.user_id)
        and lock['expires_at']
    )
    assert (await client.get(f'/api/v1/blog/posts/{pid}')).json()['locked_by'] == str(
        test_org.user_id
    )
    assert (await client.delete(f'/api/v1/blog/posts/{pid}/lock')).status_code == 204
    assert 'locked_by' not in (await client.get(f'/api/v1/blog/posts/{pid}')).json()

    # soft delete
    assert (await client.delete(f'/api/v1/blog/posts/{pid}')).status_code == 204
    assert (await client.get(f'/api/v1/blog/posts/{pid}')).status_code == 404
    assert pid not in [
        p['id']
        for p in (await client.get(f'/api/v1/blog/blogs/{bid}/posts')).json()['items']
    ]


async def test_blog_0104_0300_metadata_taxonomy_filters_and_counts(
    client: httpx.AsyncClient, test_org
):
    blog = await _blog(client)
    bid = blog['id']
    news = (
        await client.post(
            f'/api/v1/blog/blogs/{bid}/categories', json={'name': 'Company news'}
        )
    ).json()
    guides = (
        await client.post(
            f'/api/v1/blog/blogs/{bid}/categories',
            json={'name': 'Guides', 'slug': 'how-to'},
        )
    ).json()
    assert news['slug'] == 'company-news' and guides['position'] == 1
    assert (
        await client.post(
            f'/api/v1/blog/blogs/{bid}/categories', json={'name': 'X', 'slug': 'how-to'}
        )
    ).status_code == 409
    reordered = await client.patch(
        f'/api/v1/blog/blogs/{bid}/categories/{guides["id"]}', json={'position': 0}
    )
    assert reordered.json().get('position', 0) == 0
    assert [
        c['slug']
        for c in (await client.get(f'/api/v1/blog/blogs/{bid}/categories')).json()
    ] == ['how-to', 'company-news']
    python = (
        await client.post(f'/api/v1/blog/blogs/{bid}/tags', json={'name': 'Python'})
    ).json()
    seo_tag = (
        await client.post(f'/api/v1/blog/blogs/{bid}/tags', json={'name': 'SEO'})
    ).json()
    guest = await client.post(
        f'/api/v1/blog/blogs/{bid}/authors',
        json={
            'display_name': 'Guest Writer',
            'bio': 'Freelance',
            'links': [{'label': 'Site', 'url': 'https://guest.test'}],
        },
    )
    assert guest.status_code == 201 and 'user_id' not in guest.json()
    stranger = await client.post(
        f'/api/v1/blog/blogs/{bid}/authors',
        json={'display_name': 'Nope', 'user_id': str(uuid.uuid4())},
    )
    assert stranger.status_code == 400

    asset = await client.post(
        '/api/v1/media/assets', files={'file': ('cover.png', _png(), 'image/png')}
    )
    assert asset.status_code == 201, asset.text
    aid = asset.json()['id']

    post = await _post(client, bid, title='Ten tips for SEO', doc=_doc('Body'))
    pid = post['id']
    res = await client.patch(
        f'/api/v1/blog/posts/{pid}',
        json={
            'subtitle': 'A short guide',
            'excerpt': 'Rank better.',
            'slug': 'seo-tips',
            'category_id': guides['id'],
            'tag_ids': [python['id'], seo_tag['id'], python['id']],
            'author_ids': [guest.json()['id']],
            'cover_asset_id': aid,
            'cover_alt': 'A teal square',
            'featured': True,
            'noindex': True,
            'seo': {
                'title': 'SEO tips',
                'description': 'Ten tips',
                'canonical': 'https://acme.test/seo',
                'og_image': f'asset:{aid}',
            },
        },
    )
    assert res.status_code == 200, res.text
    out = res.json()
    assert (
        out['slug'] == 'seo-tips'
        and out['category']['slug'] == 'how-to'
        and out['featured'] is True
    )
    assert [t['name'] for t in out['tags']] == ['Python', 'SEO']
    assert [a['display_name'] for a in out['authors']] == ['Guest Writer']
    assert (
        out['cover_asset_id'] == aid
        and out['seo']['og_image'] == f'asset:{aid}'
        and out['noindex'] is True
    )
    usages = (await client.get(f'/api/v1/media/assets/{aid}/usages')).json()
    assert any(u.get('app') == 'blog' for u in usages), usages

    for bad in (
        {'cover_asset_id': str(uuid.uuid4())},
        {'category_id': str(uuid.uuid4())},
        {'tag_ids': [str(uuid.uuid4())]},
        {'seo': {'canonical': 'relative/path'}},
        {'slug': 'Not A Slug'},
    ):
        assert (
            await client.patch(f'/api/v1/blog/posts/{pid}', json=bad)
        ).status_code == 400, bad
    other = await _post(client, bid, title='Other')
    assert (
        await client.patch(
            f'/api/v1/blog/posts/{other["id"]}', json={'slug': 'seo-tips'}
        )
    ).status_code == 409
    # null clears a nullable field (absent = unchanged)
    set_cat = await client.patch(
        f'/api/v1/blog/posts/{other["id"]}',
        json={'category_id': news['id'], 'excerpt': 'E'},
    )
    assert set_cat.json()['category']['id'] == news['id']
    cleared = await client.patch(
        f'/api/v1/blog/posts/{other["id"]}', json={'category_id': None, 'excerpt': None}
    )
    assert 'category' not in cleared.json() and 'excerpt' not in cleared.json()

    # filters + counts of the quick tabs
    await client.post(f'/api/v1/blog/posts/{other["id"]}/submit')
    listed = (await client.get(f'/api/v1/blog/blogs/{bid}/posts')).json()
    assert listed['total'] == 2 and listed['counts']['all'] == 2
    assert listed['counts']['draft'] == 1 and listed['counts']['in_review'] == 1
    assert [
        p['id']
        for p in (
            await client.get(
                f'/api/v1/blog/blogs/{bid}/posts', params={'status': 'in_review'}
            )
        ).json()['items']
    ] == [other['id']]
    by = {
        'tag_id': python['id'],
        'category_id': guides['id'],
        'author_id': guest.json()['id'],
        'q': 'tips',
        'featured': 'true',
    }
    for key, value in by.items():
        page = (
            await client.get(f'/api/v1/blog/blogs/{bid}/posts', params={key: value})
        ).json()
        assert [p['id'] for p in page['items']] == [pid], key
    page = (
        await client.get(f'/api/v1/blog/blogs/{bid}/posts', params={'q': '100%_'})
    ).json()
    assert page['items'] == [] and page['counts']['all'] == 0
    assert (
        await client.get(f'/api/v1/blog/blogs/{bid}/posts', params={'status': 'bogus'})
    ).status_code == 400
    titles = [
        p['title']
        for p in (
            await client.get(
                f'/api/v1/blog/blogs/{bid}/posts', params={'sort': 'title'}
            )
        ).json()['items']
    ]
    assert titles == ['Other', 'Ten tips for SEO']

    # taxonomy counts and deletes
    assert {
        t['name']: t.get('post_count', 0)
        for t in (await client.get(f'/api/v1/blog/blogs/{bid}/tags')).json()
    } == {'Python': 1, 'SEO': 1}
    in_use = await client.delete(
        f'/api/v1/blog/blogs/{bid}/authors/{guest.json()["id"]}'
    )
    assert (
        in_use.status_code == 409 and in_use.json()['extra']['code'] == 'author_in_use'
    )
    assert (
        await client.delete(f'/api/v1/blog/blogs/{bid}/categories/{guides["id"]}')
    ).status_code == 204
    assert (
        await client.delete(f'/api/v1/blog/blogs/{bid}/tags/{python["id"]}')
    ).status_code == 204
    out = (await client.get(f'/api/v1/blog/posts/{pid}')).json()
    assert 'category' not in out and [t['name'] for t in out['tags']] == ['SEO']


# --- workflow (Blog-0102 / Blog-0103) ------------------------------------------------------------------


async def test_blog_0102_0103_workflow_publish_update_schedule(
    client: httpx.AsyncClient, test_org, sql
):
    from ews.blog import publish_due

    blog = await _blog(client)
    post = await _post(client, blog['id'], title='Launch', doc=_doc('First version'))
    pid = post['id']
    url = f'/api/v1/blog/posts/{pid}'

    assert (await client.post(f'{url}/submit')).json()['status'] == 'in_review'
    again = await client.post(f'{url}/submit')
    assert (
        again.status_code == 409
        and again.json()['extra']['code'] == 'invalid_transition'
    )
    assert (
        await client.post(f'{url}/request-changes', json={'comment': ' '})
    ).status_code == 400
    changes = (
        await client.post(f'{url}/request-changes', json={'comment': 'Add a picture'})
    ).json()
    assert changes['status'] == 'draft' and changes['review_comment'] == 'Add a picture'
    await client.post(f'{url}/submit')
    approved = (await client.post(f'{url}/approve', json={})).json()
    assert (
        approved['status'] == 'published'
        and approved['published_revision_id'] == approved['draft_revision_id']
    )
    assert 'review_comment' not in approved and not approved.get('has_changes')
    first_published_at = approved['published_at']
    live = approved['published_revision_id']

    # editing a published post: a new draft revision, the live one stays until Update
    await client.put(f'{url}/draft', json={'doc': _doc('Second version')})
    edited = (await client.get(url)).json()
    assert (
        edited['status'] == 'published'
        and edited['has_changes'] is True
        and edited['published_revision_id'] == live
    )
    meta_only = await _post(client, blog['id'], title='Meta only')
    await client.post(f'/api/v1/blog/posts/{meta_only["id"]}/publish')
    retitled = (
        await client.patch(
            f'/api/v1/blog/posts/{meta_only["id"]}', json={'excerpt': 'New excerpt'}
        )
    ).json()
    assert retitled['has_changes'] is True
    updated = (await client.post(f'{url}/publish')).json()
    assert updated['published_revision_id'] != live and not updated.get('has_changes')
    assert updated['published_at'] == first_published_at
    snapshot = (
        await client.get(f'{url}/revisions/{updated["published_revision_id"]}')
    ).json()
    assert (
        snapshot['is_published']
        and snapshot['doc'] == _doc('Second version')
        and snapshot['meta']['slug'] == 'launch'
    )

    # unpublish → unpublished; schedule in a time zone; the scheduler publishes due posts once
    assert (await client.post(f'{url}/unpublish')).json()['status'] == 'unpublished'
    past = await client.post(
        f'{url}/schedule',
        json={'scheduled_at': '2020-01-01T09:00:00', 'timezone': 'Europe/Paris'},
    )
    assert past.status_code == 400
    assert (
        await client.post(
            f'{url}/schedule',
            json={'scheduled_at': '2099-01-01T09:00:00', 'timezone': 'Mars/Base'},
        )
    ).status_code == 400
    scheduled = (
        await client.post(
            f'{url}/schedule',
            json={'scheduled_at': '2099-06-01T09:00:00', 'timezone': 'Europe/Paris'},
        )
    ).json()
    assert (
        scheduled['status'] == 'scheduled'
        and scheduled['schedule_timezone'] == 'Europe/Paris'
    )
    assert scheduled['scheduled_at'].startswith('2099-06-01T07:00:00')
    assert await publish_due(tenant_id=test_org.tenant_id) == []
    due = datetime.now(UTC) - timedelta(minutes=1)
    await sql(
        'update taas_blog_posts set scheduled_at = :at where id = :id',
        {'at': due, 'id': pid},
    )
    assert await publish_due(tenant_id=test_org.tenant_id) == [uuid.UUID(pid)]
    assert await publish_due(tenant_id=test_org.tenant_id) == []  # idempotent
    published = (await client.get(url)).json()
    assert published['status'] == 'published' and 'scheduled_at' not in published
    assert published['published_at'] == first_published_at

    # approve with a date = schedule; unpublish cancels it
    second = await _post(client, blog['id'], title='Later')
    await client.post(f'/api/v1/blog/posts/{second["id"]}/submit')
    later = (
        await client.post(
            f'/api/v1/blog/posts/{second["id"]}/approve',
            json={'scheduled_at': '2099-01-01T10:00:00+00:00'},
        )
    ).json()
    assert later['status'] == 'scheduled'
    assert (await client.post(f'/api/v1/blog/posts/{second["id"]}/unpublish')).json()[
        'status'
    ] == 'draft'

    # archive hides from the default list; unarchive → unpublished (it was published once)
    assert (await client.post(f'{url}/archive')).json()['status'] == 'archived'
    listed = (await client.get(f'/api/v1/blog/blogs/{blog["id"]}/posts')).json()
    assert (
        pid not in [p['id'] for p in listed['items']]
        and listed['counts']['archived'] == 1
    )
    assert (await client.post(f'{url}/publish')).status_code == 409
    assert (await client.post(f'{url}/unarchive')).json()['status'] == 'unpublished'


# --- permission matrix (IAM mode) -----------------------------------------------------------------------


@pytest.fixture
async def people(test_org, sql):
    """Users of the test organization (directory accounts + memberships), removed afterwards."""
    from ews.authz import revoke_domain

    suffix = uuid.uuid4().hex[:8]
    users: dict[str, tuple[uuid.UUID, str]] = {}
    for key in ('editor', 'author', 'author2', 'viewer', 'member'):
        uid, sub = uuid.uuid4(), f'sub-blog-{key}-{suffix}'
        users[key] = (uid, sub)
        await sql(
            'insert into taas_user_account (id, email, username, name, email_verified, joined_at, login_count, '
            'is_root_account, failed_reset_attempts, mfa_enabled, created_at, updated_at, tenant_id, directory_id) '
            'values (:id, :email, :email, :name, true, current_date, 0, false, 0, false, now(), now(), :t, :sub)',
            {
                'id': uid,
                'email': f'{key}-{suffix}@example.test',
                'name': key.title(),
                't': test_org.tenant_id,
                'sub': sub,
            },
        )
    from foundation.db.advanced_db_manager import MainDatabase
    from sqlalchemy import text

    async with MainDatabase.get_instance().get_engine().connect() as conn:
        admin_sub = (
            await conn.execute(
                text('select directory_id from taas_user_account where id = :id'),
                {'id': test_org.user_id},
            )
        ).scalar_one()
    users['admin'] = (test_org.user_id, admin_sub)
    for uid, _ in users.values():
        await sql(
            'insert into taas_organization_members (id, user_id, organization_id, tenant_id, role, is_owner, created_at, '
            "updated_at, joined_via) values (:id, :u, :o, :t, 'org_member', false, now(), now(), 'admin') on conflict do nothing",
            {
                'id': uuid.uuid4(),
                'u': uid,
                'o': test_org.organization_id,
                't': test_org.tenant_id,
            },
        )
    yield users
    org = f'org:{test_org.organization_id}'
    for key, (uid, _) in users.items():
        await revoke_domain(org, user_id=uid)
        if key != 'admin':
            await sql(
                'delete from taas_casbin_rule where ptype = :g and v0 = :u',
                {'g': 'g', 'u': str(uid)},
            )
            await sql(
                'delete from taas_organization_members where user_id = :u', {'u': uid}
            )
            await sql('delete from taas_user_account where id = :u', {'u': uid})


async def test_blog_permission_matrix_in_iam_mode(app, test_org, people):
    """Admin manages members; editor edits / reviews / publishes; author edits only own (or credited) posts and
    submits but cannot publish; viewer reads drafts only; organization member without a role and a foreign
    organization see nothing (404)."""
    from ews.authz import grant, revoke_domain
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

    org = f'org:{test_org.organization_id}'
    for key, (uid, _) in people.items():
        await grant(uid, 'org_admin' if key == 'admin' else 'org_member', org)
    configure_security(settings=EwsAuthSettings(mode='iam'), verifier=Verifier())
    clients: dict[str, httpx.AsyncClient] = {}
    blog_id = None
    try:
        for key, (_, sub) in people.items():
            clients[key] = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url='http://testserver',
                headers={
                    'Authorization': f'Bearer {sub}',
                    'X-Organization-Id': str(test_org.organization_id),
                },
            )
        admin, editor, author, author2, viewer, member = (
            clients[k]
            for k in ('admin', 'editor', 'author', 'author2', 'viewer', 'member')
        )

        # organization member without a blog role: no app, no blogs, no create
        assert (await member.get('/api/v1/blog/access')).json() == {
            'allowed': False,
            'can_create': False,
            'organization_slug': test_org.slug,
        }
        assert (
            await member.post('/api/v1/blog/blogs', json={'name': 'Nope'})
        ).status_code == 403

        # admin (org_admin) creates the blog and manages its members
        created = await admin.post('/api/v1/blog/blogs', json={'name': 'Matrix blog'})
        assert created.status_code == 201, created.text
        blog = created.json()
        blog_id = blog['id']
        assert blog['role'] == 'blog_admin'
        for key, role in (
            ('editor', 'blog_editor'),
            ('author', 'blog_author'),
            ('author2', 'blog_author'),
            ('viewer', 'blog_viewer'),
        ):
            res = await admin.put(
                f'/api/v1/blog/blogs/{blog_id}/members',
                json={'user_id': str(people[key][0]), 'role': role},
            )
            assert res.status_code == 200, res.text
        members = (await admin.get(f'/api/v1/blog/blogs/{blog_id}/members')).json()
        assert {m['role'] for m in members if not m.get('inherited')} >= {
            'blog_admin',
            'blog_editor',
            'blog_author',
            'blog_viewer',
        }
        assert (
            await admin.get(
                f'/api/v1/blog/blogs/{blog_id}/member-candidates',
                params={'q': 'example.test'},
            )
        ).status_code == 200
        assert (
            await editor.put(
                f'/api/v1/blog/blogs/{blog_id}/members',
                json={'user_id': str(people['member'][0]), 'role': 'blog_viewer'},
            )
        ).status_code == 403
        assert (
            await editor.get(f'/api/v1/blog/blogs/{blog_id}/members')
        ).status_code == 200

        # member without a role: the blog does not exist for it
        assert (await member.get('/api/v1/blog/blogs')).json() == []
        assert (await member.get(f'/api/v1/blog/blogs/{blog_id}')).status_code == 404
        assert (
            await member.get(f'/api/v1/blog/blogs/{blog_id}/posts')
        ).status_code == 404

        # author: open the app, create, edit own, submit — no publish, no review, no taxonomy, no delete
        access = (await author.get('/api/v1/blog/access')).json()
        assert access['allowed'] is True and access['can_create'] is False
        assert [b['id'] for b in (await author.get('/api/v1/blog/blogs')).json()] == [
            blog_id
        ]
        own = await author.post(
            f'/api/v1/blog/blogs/{blog_id}/posts',
            json={'title': 'Mine', 'doc': _doc('mine')},
        )
        assert own.status_code == 201, own.text
        pid = own.json()['id']
        assert (
            own.json()['can_edit'] is True
            and 'blog.post:publish' not in own.json()['permissions']
        )
        assert (
            await author.patch(f'/api/v1/blog/posts/{pid}', json={'excerpt': 'x'})
        ).status_code == 200
        assert (
            await author.put(
                f'/api/v1/blog/posts/{pid}/draft', json={'doc': _doc('mine v2')}
            )
        ).status_code == 200
        assert (
            await author.post(f'/api/v1/blog/posts/{pid}/publish')
        ).status_code == 403
        assert (
            await author.post(
                f'/api/v1/blog/posts/{pid}/schedule',
                json={'scheduled_at': '2099-01-01T00:00:00'},
            )
        ).status_code == 403
        assert (await author.delete(f'/api/v1/blog/posts/{pid}')).status_code == 403
        assert (
            await author.post(
                f'/api/v1/blog/blogs/{blog_id}/categories', json={'name': 'Nope'}
            )
        ).status_code == 403
        assert (
            await author.get(f'/api/v1/blog/blogs/{blog_id}/categories')
        ).status_code == 200
        assert (await author.post(f'/api/v1/blog/posts/{pid}/submit')).json()[
            'status'
        ] == 'in_review'
        assert (
            await author.post(
                f'/api/v1/blog/posts/{pid}/request-changes', json={'comment': 'x'}
            )
        ).status_code == 403
        assert (
            await author.post(f'/api/v1/blog/posts/{pid}/approve', json={})
        ).status_code == 403

        # another author reads but cannot edit — until it is credited on the post
        other = (await author2.get(f'/api/v1/blog/posts/{pid}')).json()
        assert not other.get('can_edit')
        assert (
            await author2.patch(f'/api/v1/blog/posts/{pid}', json={'excerpt': 'hijack'})
        ).status_code == 403
        assert (
            await author2.put(
                f'/api/v1/blog/posts/{pid}/draft', json={'doc': _doc('hijack')}
            )
        ).status_code == 403
        assert (
            await author2.post(f'/api/v1/blog/posts/{pid}/submit')
        ).status_code == 403
        theirs = (
            await author2.post(
                f'/api/v1/blog/blogs/{blog_id}/posts', json={'title': 'Theirs'}
            )
        ).json()
        co_author = theirs['authors'][0]['id']

        # editor: edits any post, reviews, publishes, manages taxonomy; the soft lock blocks concurrent saves
        assert (
            await editor.post(
                f'/api/v1/blog/blogs/{blog_id}/categories', json={'name': 'News'}
            )
        ).status_code == 201
        credited = await editor.patch(
            f'/api/v1/blog/posts/{pid}',
            json={'author_ids': [own.json()['authors'][0]['id'], co_author]},
        )
        assert credited.status_code == 200, credited.text
        assert (await author2.get(f'/api/v1/blog/posts/{pid}')).json()[
            'can_edit'
        ] is True
        assert (
            await author2.patch(
                f'/api/v1/blog/posts/{pid}', json={'excerpt': 'co-written'}
            )
        ).status_code == 200
        assert (await author.post(f'/api/v1/blog/posts/{pid}/lock', json={})).json()[
            'locked'
        ] is True
        locked = await editor.put(
            f'/api/v1/blog/posts/{pid}/draft', json={'doc': _doc('editor')}
        )
        assert locked.status_code == 409 and locked.json()['extra']['code'] == 'locked'
        assert (await editor.post(f'/api/v1/blog/posts/{pid}/lock', json={})).json()[
            'locked'
        ] is False
        assert (
            await editor.post(f'/api/v1/blog/posts/{pid}/lock', json={'force': True})
        ).json()['locked'] is True
        assert (
            await editor.put(
                f'/api/v1/blog/posts/{pid}/draft', json={'doc': _doc('editor')}
            )
        ).status_code == 200
        assert (
            await editor.post(
                f'/api/v1/blog/posts/{pid}/request-changes', json={'comment': 'Shorter'}
            )
        ).json()['status'] == 'draft'
        await author.post(f'/api/v1/blog/posts/{pid}/submit')
        assert (await editor.post(f'/api/v1/blog/posts/{pid}/approve', json={})).json()[
            'status'
        ] == 'published'
        assert (
            await editor.post(f'/api/v1/blog/posts/{theirs["id"]}/publish')
        ).status_code == 200
        assert (await editor.delete(f'/api/v1/blog/blogs/{blog_id}')).status_code == 403

        # viewer: reads drafts and published posts, changes nothing
        assert (
            await viewer.get(f'/api/v1/blog/posts/{theirs["id"]}')
        ).status_code == 200
        listed = (await viewer.get(f'/api/v1/blog/blogs/{blog_id}/posts')).json()
        assert listed['total'] == 2 and not any(
            p.get('can_edit') for p in listed['items']
        )
        assert (
            await viewer.get(f'/api/v1/blog/posts/{pid}/revisions')
        ).status_code == 200
        assert (
            await viewer.post(
                f'/api/v1/blog/blogs/{blog_id}/posts', json={'title': 'x'}
            )
        ).status_code == 403
        assert (
            await viewer.patch(f'/api/v1/blog/posts/{pid}', json={'excerpt': 'x'})
        ).status_code == 403
        assert (
            await viewer.put(f'/api/v1/blog/posts/{pid}/draft', json={'doc': _doc('x')})
        ).status_code == 403
        assert (
            await viewer.post(f'/api/v1/blog/posts/{pid}/lock', json={})
        ).status_code == 403
        assert (
            await viewer.post(f'/api/v1/blog/posts/{pid}/unpublish')
        ).status_code == 403
        assert (
            await viewer.get(f'/api/v1/blog/blogs/{blog_id}/members')
        ).status_code == 200
        assert (
            await viewer.get(f'/api/v1/blog/blogs/{blog_id}/member-candidates')
        ).status_code == 403

        # foreign organization → 404; the child organization does not see the parent's blog
        foreign = {'X-Organization-Id': str(uuid.uuid4())}
        assert (
            await admin.get('/api/v1/blog/blogs', headers=foreign)
        ).status_code == 404
        child = {'X-Organization-Id': str(test_org.child_organization_id)}
        assert (
            await admin.get(f'/api/v1/blog/blogs/{blog_id}', headers=child)
        ).status_code == 404
        assert (
            await admin.get(f'/api/v1/blog/posts/{pid}', headers=child)
        ).status_code == 404

        # admin removes a member: the blog disappears for that user
        assert (
            await admin.delete(
                f'/api/v1/blog/blogs/{blog_id}/members/{people["viewer"][0]}'
            )
        ).status_code == 204
        assert (await viewer.get(f'/api/v1/blog/blogs/{blog_id}')).status_code == 404
        assert (
            await admin.delete(
                f'/api/v1/blog/blogs/{blog_id}/members/{people["viewer"][0]}'
            )
        ).status_code == 404
        assert (
            await admin.put(
                f'/api/v1/blog/blogs/{blog_id}/members',
                json={'user_id': str(uuid.uuid4()), 'role': 'blog_viewer'},
            )
        ).status_code == 400
        assert (
            await admin.put(
                f'/api/v1/blog/blogs/{blog_id}/members',
                json={'user_id': str(people['viewer'][0]), 'role': 'org_admin'},
            )
        ).status_code == 400
    finally:
        for c in clients.values():
            await c.aclose()
        configure_security(
            settings=EwsAuthSettings(
                mode='dev', dev_organization_id=str(test_org.organization_id)
            )
        )
        if blog_id:
            await revoke_domain(f'blog:{blog_id}')


async def test_sites_and_blogs_share_the_organization_address(client):
    """Blog ADR-5: a site may not take the slug of a blog of the same organization, and the other way round."""
    blog = await client.post('/api/v1/blog/blogs', json={'name': 'Shared address', 'slug': 'shared-address'})
    assert blog.status_code in (200, 201), blog.text
    site = await client.post('/api/v1/sites/', json={'name': 'Shared address', 'slug': 'shared-address'})
    assert site.status_code == 409, site.text
    other = await client.post('/api/v1/sites/', json={'name': 'Other address', 'slug': 'other-address-site'})
    assert other.status_code in (200, 201), other.text
    clash = await client.post('/api/v1/blog/blogs', json={'name': 'Clash', 'slug': 'other-address-site'})
    assert clash.status_code == 409, clash.text
