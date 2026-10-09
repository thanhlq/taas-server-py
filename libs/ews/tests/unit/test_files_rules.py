"""File Manager pure rules (taas-specs/files/file-manager-app-spec.md): names (File-0300 keep both), types for the
quick tabs (UI §8), safe inline preview (File-0206, Sto-0202), storage keys (§6, kind ``document``), settings
(Sto-0200 URL lifetime), drive roles (File-0200, File-0306) and the shared storage override."""

from __future__ import annotations

import uuid

import pytest
from ews.access import role_permissions
from ews.files._access import DRIVES, MEMBER_ROLES, default_member_role
from ews.files._rules import (
    MAX_DEPTH,
    clean_color,
    clean_name,
    content_disposition,
    file_type,
    free_name,
    inline_allowed,
    like_pattern,
    mime_of,
    numbered,
    prefix_tsquery,
    split_ext,
    type_patterns,
    viewer_kind,
)
from ews.files._settings import FilesSettings
from ews.files._storage import preview_key, staging_key, version_key
from foundation.exceptions import ClientException


@pytest.mark.parametrize(
    'bad', ['', '   ', '.', '..', 'a/b', 'a\\b', 'tab\there', 'x' * 256, 'zero​width']
)
def test_file_0300_names_without_separators_or_control_characters(bad: str):
    with pytest.raises(ClientException):
        clean_name(bad)


def test_file_0300_names_are_trimmed_and_normalized():
    assert clean_name('  Rapport été.pdf ') == 'Rapport été.pdf'
    assert clean_name('Café') == 'Café'  # NFC


def test_file_0300_keep_both_names():
    assert split_ext('report.final.PDF') == ('report.final', 'pdf')
    assert split_ext('.env') == ('.env', None)
    assert split_ext('README') == ('README', None)
    assert numbered('report.pdf', 2) == 'report (2).pdf'
    assert numbered('README', 1) == 'README (1)'
    assert len(numbered('x' * 250 + '.pdf', 12)) <= 255
    assert free_name('a.txt', set()) == 'a.txt'
    assert free_name('A.txt', {'a.txt', 'a (1).txt'}) == 'A (2).txt'


def test_colors():
    assert clean_color('#AABBCC') == '#AABBCC'
    assert clean_color('brand-1') == 'brand-1'
    assert clean_color('') is None
    with pytest.raises(ClientException):
        clean_color('red; background:url(x)')


def test_types_from_the_name_then_the_declared_type():
    assert mime_of('scan.pdf') == 'application/pdf'
    assert mime_of('noext', 'image/png; charset=x') == 'image/png'
    assert mime_of('noext', 'not a type') == 'application/octet-stream'
    assert file_type('folder', None) == 'folder'
    assert file_type('file', 'image/png') == 'image'
    assert file_type('file', 'video/mp4') == 'video'
    assert file_type('file', 'application/pdf') == 'document'
    assert (
        file_type(
            'file',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )
        == 'document'
    )
    assert file_type('file', 'application/zip') == 'other'
    assert type_patterns('image') == ([], ['image/'])
    assert 'application/pdf' in type_patterns('document')[0]


@pytest.mark.parametrize(
    ('mime', 'inline'),
    [
        ('image/png', True),
        ('application/pdf', True),
        ('video/mp4', True),
        ('audio/mpeg', True),
        ('text/plain; charset=utf-8', True),
        ('image/svg+xml', False),
        ('text/html', False),
        ('application/javascript', False),
        ('application/octet-stream', False),
        (None, False),
    ],
)
def test_file_0206_only_safe_types_are_shown_inline(mime: str | None, inline: bool):
    assert inline_allowed(mime) is inline


def test_content_disposition_has_an_ascii_fallback_and_the_utf8_name():
    header = content_disposition('Été "draft".pdf', inline=False)
    assert header.startswith('attachment; filename="Ete draft.pdf"')
    assert "filename*=UTF-8''%C3%89t%C3%A9%20%22draft%22.pdf" in header
    assert content_disposition('a.png', inline=True).startswith('inline;')


def test_storage_keys_follow_the_document_layout():
    d, n, v = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    assert version_key(d, n, v) == f'documents/drives/{d}/{n}/{v}'
    assert staging_key(d, v) == f'documents/staging/{d}/{v}'
    assert preview_key(n, v, 'thumb') == f'derived/files/{n}/{v}/thumb.webp'


def test_sto_0200_url_lifetime_is_clamped(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv('FILES_URL_TTL_SECONDS', '3600')
    monkeypatch.setenv('FILES_DELIVERY', 'presigned')
    monkeypatch.setenv('FILES_PUBLIC_BASE_URL', 'https://api.example.test/')
    monkeypatch.setenv('FILES_VIEW_URL_TTL_HOURS', '72')
    monkeypatch.setenv('FILES_PIPELINE', 'worker')
    settings = FilesSettings.from_env()
    assert settings.url_ttl_seconds == 300
    assert settings.view_ttl_seconds == 24 * 3600  # File-0500: view URLs at most 24 h
    assert settings.delivery == 'presigned'
    assert settings.public_base_url == 'https://api.example.test'
    assert settings.pipeline == 'worker'
    assert (
        FilesSettings().pipeline == 'api' and FilesSettings().view_ttl_seconds == 86400
    )
    monkeypatch.setenv('FILES_DELIVERY', 'cdn')
    with pytest.raises(ValueError):
        FilesSettings.from_env()
    monkeypatch.setenv('FILES_DELIVERY', 'proxy')
    monkeypatch.setenv('FILES_PIPELINE', 'cron')
    with pytest.raises(ValueError):
        FilesSettings.from_env()


def test_file_0200_drive_roles_and_organization_default():
    assert DRIVES.roles == (
        'drive_manager',
        'drive_editor',
        'drive_commenter',
        'drive_viewer',
    )
    editor, viewer = role_permissions('drive_editor'), role_permissions('drive_viewer')
    # File-0306: editors upload, delete to and restore from the trash; deleting for good is the drive's.
    assert {
        'files.item:create',
        'files.item:update',
        'files.item:delete',
        'files.item:restore',
    } <= editor
    assert 'files.drive:delete' not in editor and 'files.member:manage' not in editor
    assert 'files.drive:delete' in role_permissions('drive_manager')
    assert 'files.item:create' not in viewer and 'files.item:read' in viewer
    assert MEMBER_ROLES == ('drive_editor', 'drive_viewer')

    class _Drive:
        settings: dict = {}

    drive = _Drive()
    assert default_member_role(drive) == 'drive_editor'  # type: ignore[arg-type]
    drive.settings = {'default_member_role': 'drive_viewer'}
    assert default_member_role(drive) == 'drive_viewer'  # type: ignore[arg-type]
    drive.settings = {'default_member_role': 'drive_manager'}  # not allowed → default
    assert default_member_role(drive) == 'drive_editor'  # type: ignore[arg-type]
    assert MAX_DEPTH == 20


def test_shared_storage_override():
    from ews.shared import storage_resolver, use_storage

    class _Resolver:
        pass

    resolver = _Resolver()
    previous = use_storage(resolver)  # type: ignore[arg-type]
    try:
        assert storage_resolver() is resolver
        assert use_storage(resolver) is resolver  # returns the override it replaces
    finally:
        use_storage(previous)


def test_file_0400_search_patterns_escape_like_wildcards():
    assert like_pattern('budget') == '%budget%'
    assert like_pattern('50%_off\\') == '%50\\%\\_off\\\\%'


def test_file_0400_content_queries_are_quoted_prefixes():
    assert prefix_tsquery('Invoice ACME') == "'invoice':* & 'acme':*"
    assert (
        prefix_tsquery("o'brien & | !:*") == "'o':* & 'brien':*"
    )  # no tsquery syntax from users
    assert prefix_tsquery('   ') is None and prefix_tsquery('?!') is None
    assert (
        prefix_tsquery(' '.join(f'w{i}' for i in range(20))).count('&') == 7
    )  # at most 8 words


@pytest.mark.parametrize(
    ('mime', 'kind'),
    [
        ('image/jpeg', 'image'),
        ('image/svg+xml', 'none'),
        ('application/pdf', 'pdf'),
        ('video/mp4', 'video'),
        ('audio/ogg', 'audio'),
        ('text/markdown', 'text'),
        ('application/json', 'none'),
        (None, 'none'),
    ],
)
def test_file_0302_viewer_kind(mime: str | None, kind: str):
    assert viewer_kind(mime) == kind
