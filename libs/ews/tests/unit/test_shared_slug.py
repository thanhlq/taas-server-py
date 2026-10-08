"""``ews.shared.slugify`` — the one slug rule of every app (taas-specs/blog/blog-publishing-spec.md Blog-0106)."""

from __future__ import annotations

import pytest
from ews.shared import SLUG_MAX, slugify


@pytest.mark.parametrize(
    ('text', 'slug'),
    [
        # Vietnamese: đ / Đ are not decomposed by NFKD; tones and hooks are combining marks
        ('Getting started with Đà Nẵng', 'getting-started-with-da-nang'),
        ('Đường phố Hà Nội', 'duong-pho-ha-noi'),
        ('Tiếng Việt có dấu', 'tieng-viet-co-dau'),
        # German: umlauts lose their marks, ß → ss
        ('Straße über Größe', 'strasse-uber-grosse'),
        ('ẞ GROSS', 'ss-gross'),
        # Polish: ł / Ł are not decomposed
        ('Zażółć gęślą jaźń', 'zazolc-gesla-jazn'),
        ('Łódź', 'lodz'),
        # Nordic / Icelandic / French ligatures
        ('Ærøskøbing', 'aeroskobing'),
        ('Þór og Óðinn', 'thor-og-odinn'),
        ('Œuvre complète', 'oeuvre-complete'),
        ('Café du Marché !', 'cafe-du-marche'),
        # Turkish dotless i
        ('Işık ılık', 'isik-ilik'),
        # full-width letters (NFKD compatibility forms)
        ('ＡＢＣ 123', 'abc-123'),
        # punctuation and spaces collapse to single hyphens, trimmed
        ('  --Hello,   World!--  ', 'hello-world'),
        ('a___b...c', 'a-b-c'),
    ],
)
def test_slugify_transliterates_and_cleans(text: str, slug: str):
    assert slugify(text) == slug


def test_slugify_without_latin_letters_is_empty():
    """Japanese / Arabic / emoji titles: the caller picks its fallback (``post``, ``page`` …)."""
    assert slugify('日本語のタイトル') == ''
    assert slugify('مرحبا') == ''
    assert slugify('🚀🚀') == ''
    assert slugify('') == ''
    assert slugify('東京 2026') == '2026'


def test_slugify_max_length_never_ends_with_a_hyphen():
    assert SLUG_MAX == 80
    assert len(slugify('word ' * 40)) <= 80
    assert slugify('x' * 100) == 'x' * 80
    assert slugify('abc def', 4) == 'abc'
    assert slugify('Đà Nẵng ' * 20, 36) == 'da-nang-da-nang-da-nang-da-nang-da-n'


def test_sites_knowledge_and_blog_share_the_rule():
    from ews.blog._rules import slugify as blog_slugify
    from ews.knowledge._rules import slugify as kb_slugify
    from ews.sites._rules import slugify as sites_slugify

    assert (
        blog_slugify is slugify and kb_slugify is slugify and sites_slugify is slugify
    )
