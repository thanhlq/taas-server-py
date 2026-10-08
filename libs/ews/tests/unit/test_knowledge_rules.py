"""Knowledge Center pure rules (taas-specs/knowledge/knowledge-app-spec.md): visibility → implicit viewer
(Kb-0100), page status / drafts (Kb-0103), tree depth (Kb-0300), review status (Kb-0303), templates (Kb-0301),
attachment names and signed URLs (Kb-0305), search helpers (Kb-0104)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from ews.access import object_roles, role_permissions
from ews.knowledge import KB_SPACES
from ews.knowledge._attachments import (
    clean_mime,
    content_disposition,
    file_token,
    read_file_token,
    safe_filename,
)
from ews.knowledge._document import check_document
from ews.knowledge._rules import (
    MAX_DEPTH,
    VIEWER,
    check_create_depth,
    implicit_role,
    like_pattern,
    lock_holder,
    page_status,
    review_status,
    slug_error,
    slugify,
    snippet,
    verified_until,
    visible_tree_ids,
)
from ews.knowledge._templates import get_template, templates
from foundation.exceptions import ClientException, ValidationException

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


@dataclass
class Space:
    visibility: str
    organization_id: uuid.UUID
    include_sub_orgs: bool = False


@dataclass
class Page:
    draft_revision_id: uuid.UUID | None = None
    published_revision_id: uuid.UUID | None = None
    locked_by: uuid.UUID | None = None
    locked_until: datetime | None = None


def test_kb_space_roles_come_from_the_catalog():
    assert KB_SPACES.roles == ('kb_space_admin', 'kb_space_editor', 'kb_space_viewer')
    assert [r.key for r in object_roles(KB_SPACES) if r.default] == ['kb_space_editor']
    assert KB_SPACES.domain('x') == 'kb-space:x'
    viewer = role_permissions(VIEWER)
    assert {
        'kb.space:read',
        'kb.page:read',
    } <= viewer and 'kb.page:update' not in viewer
    assert 'kb.space_member:manage' not in role_permissions('kb_space_editor')
    assert 'kb.space_member:manage' in role_permissions('kb_space_admin')


def test_kb0100_visibility_grants_the_implicit_viewer_role():
    root, child, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    root_path, child_path = f'/{root}/', f'/{root}/{child}/'
    in_root, in_child, in_other = (
        [(root, root_path)],
        [(child, child_path)],
        [(other, f'/{other}/')],
    )
    assert implicit_role(Space('tenant', root), root_path, []) == VIEWER
    org = Space('organization', root)
    assert implicit_role(org, root_path, in_root) == VIEWER
    assert implicit_role(org, root_path, in_child) is None
    assert (
        implicit_role(
            Space('organization', root, include_sub_orgs=True), root_path, in_child
        )
        == VIEWER
    )
    assert implicit_role(org, root_path, in_other) is None
    assert implicit_role(Space('restricted', root), root_path, in_root) is None


def test_kb0103_page_status_and_soft_lock():
    a, b = uuid.uuid4(), uuid.uuid4()
    assert page_status(Page(draft_revision_id=a)) == 'draft'
    assert (
        page_status(Page(draft_revision_id=a, published_revision_id=a)) == 'published'
    )
    assert page_status(Page(draft_revision_id=b, published_revision_id=a)) == 'changed'
    user = uuid.uuid4()
    assert (
        lock_holder(Page(locked_by=user, locked_until=NOW + timedelta(seconds=30)), NOW)
        == user
    )
    assert (
        lock_holder(Page(locked_by=user, locked_until=NOW - timedelta(seconds=1)), NOW)
        is None
    )


def test_kb0300_tree_depth_and_reader_visibility():
    check_create_depth(None)
    check_create_depth(MAX_DEPTH - 2)
    with pytest.raises(ClientException):
        check_create_depth(MAX_DEPTH - 1)
    root, child, grandchild, lone = (uuid.uuid4() for _ in range(4))
    rows = [
        (root, None, True),
        (lone, None, False),
        (child, lone, True),
        (grandchild, root, True),
    ]
    assert visible_tree_ids(rows) == {root, grandchild}


def test_kb0303_review_status():
    assert review_status(None, None, NOW) == 'unverified'
    assert review_status(NOW, None, NOW) == 'verified'
    assert review_status(NOW, NOW + timedelta(days=60), NOW) == 'verified'
    assert review_status(NOW, NOW + timedelta(days=10), NOW) == 'due'
    assert review_status(NOW, NOW - timedelta(days=1), NOW) == 'expired'
    assert verified_until(NOW, 30) == NOW + timedelta(days=30)
    assert verified_until(NOW, None) is None and verified_until(None, 30) is None


def test_slugs():
    assert slugify('Équipe RH — Procédures', 60) == 'equipe-rh-procedures'
    assert slug_error('hr-policies', 60) is None
    assert slug_error('HR', 60) and slug_error('a--b', 60) and slug_error('x' * 61, 60)


def test_kb0301_templates_are_valid_site_documents():
    keys = [t['key'] for t in templates()]
    assert keys == [
        'sop',
        'policy',
        'how-to',
        'faq',
        'meeting-notes',
        'decision-record',
    ]
    for template in templates():
        assert (
            template['name']
            and template['description']
            and template['icon']
            and template['title']
        )
        check_document(template['doc'])
    copy = get_template('faq')
    copy['doc']['sections'].clear()
    assert get_template('faq')['doc']['sections'], 'get_template returns a copy'
    with pytest.raises(ClientException):
        get_template('nope')
    with pytest.raises(ValidationException):
        check_document({'schemaVersion': 1, 'sections': [{'id': 'x', 'type': 'nope'}]})


def test_kb0305_attachment_names_types_and_tokens():
    assert safe_filename('../../etc/passwd') == 'passwd'
    assert safe_filename('C:\\temp\\"Q3".pdf') == 'Q3.pdf'
    assert safe_filename('') == 'file'
    assert clean_mime('application/pdf; charset=binary', 'x.pdf') == 'application/pdf'
    assert clean_mime(None, 'notes.txt') == 'text/plain'
    assert clean_mime('application/octet-stream', 'scan.png') == 'image/png'
    assert clean_mime('not a mime', 'blob') == 'application/octet-stream'
    disposition = content_disposition('Résumé "final".pdf')
    assert (
        disposition.startswith('attachment; filename="Rsum final.pdf"')
        and "UTF-8''R%C3%A9sum%C3%A9" in disposition
    )

    @dataclass
    class Attachment:
        tenant_id: uuid.UUID
        key: str
        mime: str
        filename: str

    att = Attachment(
        uuid.uuid4(), 'knowledge/s/a/1/original.pdf', 'application/pdf', 'Q3.pdf'
    )
    exp = int(NOW.timestamp()) + 10**9
    claims = read_file_token(file_token(att, inline=False, exp=exp))
    assert claims and claims['k'] == att.key and claims['d'] == 'Q3.pdf'
    assert 'd' not in (read_file_token(file_token(att, inline=True, exp=exp)) or {})
    assert read_file_token(file_token(att, inline=False, exp=1)) is None
    assert read_file_token('forged.token') is None


def test_kb0104_search_helpers():
    assert like_pattern('50%_off\\') == '%50\\%\\_off\\\\%'
    text = (
        'Intro. ' + 'x ' * 200 + 'the expense policy applies to travel. ' + 'y ' * 200
    )
    found = snippet(text, ['EXPENSE'])
    assert 'expense policy' in found and found.startswith('…') and found.endswith('…')
    assert snippet(None, ['x']) == ''
