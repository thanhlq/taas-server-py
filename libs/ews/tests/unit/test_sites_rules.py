"""Site builder pure rules: document validation (Site-0103), slugs, theme contrast, menus, redirects,
accessibility, starter templates."""

from __future__ import annotations

import uuid

import pytest
from ews.sites._document import asset_ids, block_catalog, page_ids, plain_text, validate_document
from ews.sites._rules import (
    accessibility_issues,
    contrast_ratio,
    creates_loop,
    normalize_menu,
    normalize_theme,
    page_slug_error,
    site_slug_error,
    slugify,
    theme_contrast_issues,
)
from ews.sites._templates import templates

ASSET = f'asset:{uuid.uuid4()}'


def _doc(*blocks):
    return {'schemaVersion': 1, 'sections': list(blocks)}


def test_valid_document_with_nesting_and_rich_text():
    doc = _doc(
        {'id': 'h', 'type': 'hero', 'props': {'title': 'Fresh coffee', 'image': ASSET, 'primaryHref': '/menu'}},
        {'id': 's', 'type': 'section', 'props': {'background': 'muted'}, 'children': [
            {'id': 'c', 'type': 'columns', 'children': [
                {'id': 'c1', 'type': 'column', 'children': [
                    {'id': 'r', 'type': 'richText', 'content': {'type': 'doc', 'content': [
                        {'type': 'paragraph', 'content': [{'type': 'text', 'text': 'Hi', 'marks': [{'type': 'link', 'attrs': {'href': 'https://x.com'}}]}]},
                    ]}},
                ]},
            ]},
        ]},
    )
    assert validate_document(doc) == []
    assert asset_ids(doc) == {uuid.UUID(ASSET[6:])}
    assert 'Fresh coffee' in plain_text(doc) and 'Hi' in plain_text(doc)


@pytest.mark.parametrize(
    ('block', 'message'),
    [
        ({'id': 'x', 'type': 'nope'}, 'unknown block type'),
        ({'id': 'x', 'type': 'heading', 'props': {}}, 'is required'),
        ({'id': 'x', 'type': 'heading', 'props': {'text': 'a', 'level': 7}}, 'between'),
        ({'id': 'x', 'type': 'heading', 'props': {'text': 'a', 'color': 'red'}}, 'unknown property'),
        ({'id': 'x', 'type': 'button', 'props': {'label': 'Go', 'href': 'javascript:alert(1)'}}, 'link'),
        ({'id': 'x', 'type': 'image', 'props': {'image': 'https://evil/img.png'}}, 'media reference'),
        ({'id': 'x', 'type': 'column', 'children': []}, 'top level'),
        ({'id': 'x', 'type': 'section', 'children': [{'id': 'y', 'type': 'section'}]}, 'inside section'),
        ({'id': 'x', 'type': 'richText', 'content': {'type': 'doc', 'content': [{'type': 'image'}]}}, 'unsupported rich text'),
        ({'id': 'bad id!', 'type': 'spacer'}, 'id must be'),
    ],
)
def test_invalid_documents(block, message):
    issues = [str(i) for i in validate_document(_doc(block))]
    assert any(message in i for i in issues), issues


def test_duplicate_ids_and_limits():
    issues = [str(i) for i in validate_document(_doc({'id': 'a', 'type': 'spacer'}, {'id': 'a', 'type': 'divider'}))]
    assert any('duplicate' in i for i in issues)
    many = _doc(*({'id': f'b{i}', 'type': 'spacer'} for i in range(block_catalog()['limits']['maxBlocks'] + 1)))
    assert any('at most' in str(i) for i in validate_document(many))


def test_page_references():
    pid = uuid.uuid4()
    doc = _doc({'id': 'b', 'type': 'button', 'props': {'label': 'About', 'href': f'page:{pid}'}})
    assert validate_document(doc) == [] and page_ids(doc) == {pid}


def test_slugs():
    assert site_slug_error('site1') is None
    assert site_slug_error('a') and site_slug_error('-bad') and site_slug_error('_assets')
    assert page_slug_error('about-us') is None
    assert page_slug_error('About') and page_slug_error('a--b')
    assert slugify('Café du Marché !') == 'cafe-du-marche'


def test_theme_normalization_and_contrast():
    theme, errors = normalize_theme({'colors': {'primary': '#FF0000', 'text': 'red'}, 'fonts': {'body': 'Comic'}, 'radius': 'xl'})
    assert theme['colors']['primary'] == '#ff0000'
    assert len(errors) == 3
    assert contrast_ratio('#000000', '#ffffff') == 21.0
    low, _ = normalize_theme({'colors': {'text': '#aaaaaa', 'background': '#ffffff'}})
    assert any(i.code == 'contrast' for i in theme_contrast_issues(low))


def test_menus_have_two_levels():
    items, errors = normalize_menu([{'label': 'A', 'url': '/a', 'children': [{'label': 'B', 'url': '/b', 'children': [{'label': 'C', 'url': '/c'}]}]}])
    assert errors and items[0]['children'][0]['label'] == 'B'
    _, errors = normalize_menu([{'label': 'X', 'url': 'javascript:1'}])
    assert errors


def test_redirect_loops():
    assert creates_loop({'/b': '/a'}, '/a', '/b')
    assert not creates_loop({'/b': '/c'}, '/a', '/b')


def test_accessibility_report():
    doc = _doc(
        {'id': 'i', 'type': 'image', 'props': {'image': ASSET}},
        {'id': 'h1', 'type': 'heading', 'props': {'text': 'Title', 'level': 1}},
        {'id': 'h4', 'type': 'heading', 'props': {'text': 'Deep', 'level': 4}},
    )
    issues = accessibility_issues(doc, asset_alts={})
    assert {i.code for i in issues} >= {'missing_alt', 'heading_order'}
    assert not [i for i in accessibility_issues(doc, asset_alts={ASSET: 'A cup'}) if i.code == 'missing_alt']


def test_starter_templates_are_valid():
    keys = set()
    for template in templates():
        keys.add(template['key'])
        _, errors = normalize_theme(template['theme'])
        assert errors == [], template['key']
        assert sum(1 for p in template['pages'] if p.get('home')) == 1
        for page in template['pages']:
            assert validate_document(page['doc']) == [], (template['key'], page['key'])
    assert keys == {'blank', 'business', 'cafe', 'portfolio'}
