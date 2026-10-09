"""Blog pure rules (taas-specs/blog/blog-app-spec.md): status machine (Blog-0102 / 0103), own-post rule, slugs,
reading time, settings, author links, schedule instants, blog roles; shared SEO cleaning (Blog-0300)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from ews.access import object_roles, role_permissions
from ews.blog import BLOG
from ews.blog._rules import (
    ACTIONS,
    MAX_FORMER_SLUGS,
    POST_STATUSES,
    RESERVED_POST_SLUGS,
    InvalidTransition,
    blog_slug_error,
    can_edit,
    clean_links,
    clean_settings,
    content_digest,
    is_own,
    locale_error,
    post_slug_error,
    public_settings,
    public_slugs,
    reading_time,
    remember_slug,
    schedule_instant,
    snapshot_asset_refs,
    snapshot_post,
    term_slug_error,
    transition,
)
from ews.shared import clean_seo
from foundation.exceptions import ClientException

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


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


# --- status machine (Blog-0102 / Blog-0103) -----------------------------------------------------------


def test_blog_0102_review_loop():
    assert transition('submit', 'draft') == 'in_review'
    assert transition('request_changes', 'in_review') == 'draft'
    assert transition('approve', 'in_review') == 'published'
    assert transition('approve', 'in_review', scheduled=True) == 'scheduled'
    assert transition('submit', 'unpublished') == 'in_review'


def test_blog_0102_publish_from_every_live_or_editable_status():
    for status in ('draft', 'in_review', 'scheduled', 'published', 'unpublished'):
        assert transition('publish', status) == 'published'
    with pytest.raises(InvalidTransition):
        transition('publish', 'archived')


def test_blog_0103_schedule_and_cancel():
    assert transition('schedule', 'draft') == 'scheduled'
    assert transition('schedule', 'scheduled') == 'scheduled'  # reschedule
    with pytest.raises(InvalidTransition):
        transition('schedule', 'published')  # live post: publish the update instead
    # unpublish a scheduled post = cancel the schedule
    assert transition('unpublish', 'scheduled') == 'draft'
    assert transition('unpublish', 'scheduled', was_published=True) == 'unpublished'
    assert transition('unpublish', 'published') == 'unpublished'


def test_archive_and_unarchive():
    assert transition('archive', 'published') == 'archived'
    assert transition('unarchive', 'archived') == 'draft'
    assert transition('unarchive', 'archived', was_published=True) == 'unpublished'
    with pytest.raises(InvalidTransition):
        transition('archive', 'archived')


@pytest.mark.parametrize(
    ('action', 'status'),
    [
        ('submit', 'in_review'),
        ('submit', 'published'),
        ('request_changes', 'draft'),
        ('approve', 'draft'),
        ('unpublish', 'draft'),
    ],
)
def test_invalid_transitions(action, status):
    with pytest.raises(InvalidTransition, match='cannot'):
        transition(action, status)


def test_every_action_targets_known_statuses():
    assert all(set(statuses) <= set(POST_STATUSES) for statuses in ACTIONS.values())
    with pytest.raises(InvalidTransition):
        transition('teleport', 'draft')


# --- own-post rule ------------------------------------------------------------------------------------


def test_own_post_rule_creator_or_credited_author():
    me, other = uuid.uuid4(), uuid.uuid4()
    assert is_own(me, me, [])
    assert is_own(me, other, [None, me])
    assert not is_own(me, other, [other, None])


def test_can_edit_needs_update_or_update_own_on_own_post():
    assert can_edit({'blog.post:update'}, own=False)
    assert can_edit({'blog.post:update_own'}, own=True)
    assert not can_edit({'blog.post:update_own'}, own=False)
    assert not can_edit({'blog.post:read'}, own=True)


def test_blog_roles_from_the_catalog():
    assert BLOG.roles == ('blog_admin', 'blog_editor', 'blog_author', 'blog_viewer')
    assert [r.key for r in object_roles(BLOG) if r.default] == ['blog_author']
    author = role_permissions('blog_author')
    assert {'blog.post:create', 'blog.post:update_own', 'blog.post:submit'} <= author
    assert (
        not {
            'blog.post:update',
            'blog.post:publish',
            'blog.post:review',
            'blog.taxonomy:manage',
        }
        & author
    )
    editor = role_permissions('blog_editor')
    assert {'blog.post:publish', 'blog.post:review', 'blog.taxonomy:manage'} <= editor
    assert (
        'blog.member:manage' not in editor
        and 'blog.member:manage' in role_permissions('blog_admin')
    )
    assert role_permissions('blog_viewer') >= {'blog.post:read', 'blog.blog:read'}
    assert not any(
        p.endswith((':update', ':update_own', ':create'))
        for p in role_permissions('blog_viewer')
    )


# --- slugs, locale ------------------------------------------------------------------------------------


def test_slugs():
    assert blog_slug_error('news') is None
    assert blog_slug_error('a') is not None  # 2-40 characters
    assert blog_slug_error('_assets') is not None
    assert post_slug_error('hello-world-2') is None
    assert post_slug_error('Hello World') is not None
    assert post_slug_error('a--b') is not None
    assert post_slug_error('x' * 81) is not None


def test_blog_0109_reserved_post_slugs():
    """Paths of the public blog (pagination, lists, feeds) and the site reserved paths."""
    assert {
        'page',
        'category',
        'tag',
        'author',
        'feed.xml',
        'feed.json',
    } <= RESERVED_POST_SLUGS
    assert {'_assets', 'sitemap.xml', 'robots.txt'} <= RESERVED_POST_SLUGS
    for slug in ('page', 'category', 'tag', 'author'):
        assert 'reserved' in (post_slug_error(slug) or '')
        assert term_slug_error(slug) is None  # a category or tag may be called "page"
    assert post_slug_error('feed.xml') is not None  # never a valid slug anyway
    assert post_slug_error('pages') is None and post_slug_error('feed') is None


def test_blog_0108_former_slugs():
    assert remember_slug([], 'hello', 'hello-world') == ['hello']
    assert remember_slug(['a', 'b'], 'c', 'd') == ['a', 'b', 'c']
    # back to a former address: it is current again (no redirect to itself); no duplicates
    assert remember_slug(['a', 'b'], 'c', 'a') == ['b', 'c']
    assert remember_slug(['a', 'a', 'b'], 'b', 'c') == ['a', 'b']
    assert remember_slug(['a'], 'b', 'b') == ['a']
    many = [f's{i}' for i in range(30)]
    kept = remember_slug(many, 'last', 'new')
    assert len(kept) == MAX_FORMER_SLUGS and kept[-1] == 'last' and kept[0] == 's11'


def test_locale():
    assert locale_error('en') is None and locale_error('pt-BR') is None
    assert locale_error('English') is not None and locale_error('') is not None


# --- reading time -------------------------------------------------------------------------------------


def test_reading_time_from_the_document():
    assert reading_time({'schemaVersion': 1, 'sections': []}) == (0, 0)
    assert reading_time(_doc('Hello world')) == (2, 1)
    words, minutes = reading_time(_doc(' '.join(['word'] * 460), "it's well-known"))
    assert words == 462 and minutes == 2  # 2.01 → 2 (rounded, like the web editor)
    assert reading_time(_doc(' '.join(['word'] * 575)))[1] == 3  # 2.5 → 3
    assert (
        reading_time(_doc('ブログ記事 hello'))[0] == 6
    )  # kana / CJK characters count as words
    heading = {
        'schemaVersion': 1,
        'sections': [
            {'id': 'h', 'type': 'heading', 'props': {'text': 'Three short words'}}
        ],
    }
    assert reading_time(heading)[0] == 3
    # rich text tables (Site-0104): every cell counts, the header row too
    def cell(kind, text):
        return {'type': kind, 'content': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': text}]}]}

    table = {
        'schemaVersion': 1,
        'sections': [{'id': 't', 'type': 'richText', 'content': {'type': 'doc', 'content': [{'type': 'table', 'content': [
            {'type': 'tableRow', 'content': [cell('tableHeader', 'Plan'), cell('tableHeader', 'Price')]},
            {'type': 'tableRow', 'content': [cell('tableCell', 'Pro plan'), cell('tableCell', 'ten euros')]},
        ]}]}}],
    }
    assert reading_time(table)[0] == 6


# --- settings, links, SEO -----------------------------------------------------------------------------


def test_settings_are_validated():
    author = str(uuid.uuid4())
    assert clean_settings(
        {'posts_per_page': 20, 'default_author_id': author, 'feed_full_text': True}
    ) == {
        'posts_per_page': 20,
        'default_author_id': author,
        'feed_full_text': True,
    }
    assert clean_settings({'posts_per_page': None, 'ai_voice': '  '}) == {}
    for bad in (
        {'posts_per_page': 0},
        {'posts_per_page': True},
        {'feed_enabled': 'yes'},
        {'theme': {}},
        {'default_author_id': 'x'},
    ):
        with pytest.raises(ClientException):
            clean_settings(bad)


def test_author_links():
    assert clean_links([{'label': ' Site ', 'url': 'https://acme.test'}]) == [
        {'label': 'Site', 'url': 'https://acme.test'}
    ]
    assert clean_links(None) == []
    for bad in (
        [{'label': 'x', 'url': 'javascript:alert(1)'}],
        [{'label': '', 'url': 'https://a.test'}],
        [{}] * 11,
    ):
        with pytest.raises(ClientException):
            clean_links(bad)


def test_blog_0300_seo_fields():
    asset = f'asset:{uuid.uuid4()}'
    assert clean_seo(
        {'title': ' T ', 'description': '', 'og_image': asset, 'other': 1}
    ) == {'title': 'T', 'og_image': asset}
    assert clean_seo(None) == {}
    for bad in (
        {'title': 'x' * 121},
        {'canonical': '/relative'},
        {'og_image': 'https://x.test/a.png'},
    ):
        with pytest.raises(ClientException):
            clean_seo(bad)


# --- scheduling (Blog-0103) ---------------------------------------------------------------------------


def test_blog_0103_schedule_in_a_time_zone():
    instant, zone = schedule_instant(datetime(2026, 10, 9, 9, 0), 'Europe/Paris', NOW)
    assert zone == 'Europe/Paris' and instant == datetime(
        2026, 10, 9, 7, 0, tzinfo=UTC
    )  # CEST = UTC+2
    aware = datetime(2026, 10, 9, 9, 0, tzinfo=UTC)
    assert (
        schedule_instant(aware, 'Asia/Ho_Chi_Minh', NOW)[0] == aware
    )  # an offset wins over the zone
    assert schedule_instant(NOW + timedelta(minutes=5), None, NOW)[1] == 'UTC'


def test_schedule_must_be_in_the_future_with_a_known_zone():
    with pytest.raises(ClientException, match='future'):
        schedule_instant(NOW - timedelta(seconds=1), 'UTC', NOW)
    with pytest.raises(ClientException, match='time zone'):
        schedule_instant(NOW + timedelta(days=1), 'Mars/Olympus', NOW)


# --- public snapshot (blog-publishing-spec §5) --------------------------------------------------------------


def test_snapshot_slugs_current_over_former_over_gone():
    formers, gone = public_slugs(
        [('new', ['old', 'older']), ('other', ['old', 'new', 'x'])],
        [['dead', 'old'], ['zombie', 'other']],
    )
    # 'old' is claimed by the first (newest) post; 'new' is a current slug: never a redirect
    assert formers == [['old', 'older'], ['x']]
    # a deleted post's slug reused by a live post (current or former) is not gone
    assert gone == ['dead', 'zombie']
    assert public_slugs([], []) == ([], [])


def test_snapshot_post_from_the_published_revision():
    cat, tag, gone_tag, author = (str(uuid.uuid4()) for _ in range(4))
    cover = str(uuid.uuid4())
    published = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
    post = SimpleNamespace(
        id=uuid.uuid4(), slug='now-here', published_at=published, title='Draft title'
    )
    revision = SimpleNamespace(
        id=uuid.uuid4(),
        title='Live title',
        doc=_doc('one two'),
        meta={
            'slug': 'at-publish',
            'subtitle': 'Sub',
            'excerpt': 'Ex',
            'cover_asset_id': cover,
            'cover_alt': 'Alt',
            'category_id': cat,
            'tag_ids': [tag, gone_tag],
            'author_ids': [author],
            'featured': True,
            'seo': {'title': 'T', 'og_image': f'asset:{cover}'},
            'noindex': True,
            'reading_minutes': 4,
            'live_at': '2026-10-02T09:00:00+00:00',
        },
    )
    out = snapshot_post(
        post, revision, ['before'], categories={cat}, tags={tag}, authors={author}
    )
    assert out == {
        'id': str(post.id),
        'slug': 'now-here',  # the address now, not the one at publish time
        'former_slugs': ['before'],
        'title': 'Live title',  # the live version, not the draft
        'subtitle': 'Sub',
        'excerpt': 'Ex',
        'published_at': published.isoformat(),
        'updated_at': '2026-10-02T09:00:00+00:00',
        'reading_minutes': 4,
        'featured': True,
        'revision_id': str(revision.id),
        'cover': {'asset_id': cover, 'alt': 'Alt'},
        'category_id': cat,
        'tag_ids': [tag],  # deleted tag dropped
        'author_ids': [author],
        'seo': {
            'title': 'T',
            'description': None,
            'canonical': None,
            'og_image': f'asset:{cover}',
            'noindex': True,
        },
    }
    # revisions published before B3: reading time from the body, no cover, unknown category dropped
    revision.meta = {'category_id': cat}
    old = snapshot_post(post, revision, [], categories=set(), tags=set(), authors=set())
    assert old['reading_minutes'] == 1 and old['cover'] is None
    assert old['category_id'] is None and old['updated_at'] == published.isoformat()
    assert old['seo'] == {
        'title': None,
        'description': None,
        'canonical': None,
        'og_image': None,
        'noindex': False,
    }


def test_snapshot_assets_and_digest():
    a, b, c = (uuid.uuid4() for _ in range(3))
    posts = [
        {'cover': {'asset_id': str(a)}, 'seo': {'og_image': f'asset:{b}'}},
        {'cover': None, 'seo': {'og_image': None}},
    ]
    authors = [{'avatar': f'asset:{c}'}, {'avatar': None}, {'avatar': 'asset:bad'}]
    assert snapshot_asset_refs(posts, authors) == {a, b, c}
    base = {'kind': 'blog', 'posts': [1], 'release_id': 'x', 'version': 1}
    assert content_digest(base) == content_digest(
        {**base, 'release_id': 'y', 'version': 2, 'generated_at': 'now'}
    )
    assert content_digest(base) != content_digest({**base, 'posts': [2]})
    assert public_settings({'posts_per_page': 5, 'ai_voice': 'x'}) == {
        'posts_per_page': 5,
        'feed_full_text': False,
        'feed_enabled': True,
    }
