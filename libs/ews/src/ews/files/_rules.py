"""Pure rules of the File Manager (no I/O, unit-tested in ``tests/unit/test_files_rules.py``): item names,
"keep both" names, types for the quick tabs and search, safe inline preview, ``Content-Disposition``."""

from __future__ import annotations

import mimetypes
import re
import unicodedata
from typing import Literal
from urllib.parse import quote

from foundation.exceptions import ClientException

MAX_DEPTH = 20
"""Levels of the folder tree (top level = depth 0)."""
MAX_NAME = 255

type FileType = Literal['folder', 'document', 'image', 'video', 'audio', 'other']
type ViewerKind = Literal['image', 'pdf', 'video', 'audio', 'text', 'none']
type OnConflict = Literal['version', 'keep_both', 'skip']

_EXT = re.compile(r'^[a-z0-9]{1,16}$')
_MIME = re.compile(
    r'^[a-z0-9][a-z0-9!#$&^_.+-]{0,63}/[a-z0-9][a-z0-9!#$&^_.+-]{0,126}$'
)
_COLOR = re.compile(r'^(#[0-9a-fA-F]{6}|[a-z][a-z0-9-]{0,31})$')

# Shown in the browser (Content-Disposition: inline); everything else is downloaded (File-0206, Sto-0202).
_INLINE_EXACT = frozenset(
    {
        'image/png',
        'image/jpeg',
        'image/gif',
        'image/webp',
        'image/avif',
        'image/bmp',
        'application/pdf',
        'text/plain',
        'text/markdown',
        'text/csv',
    }
)
_INLINE_PREFIXES = ('video/', 'audio/')

_DOCUMENT_EXACT = frozenset(
    {
        'application/pdf',
        'application/rtf',
        'application/msword',
        'application/vnd.ms-excel',
        'application/vnd.ms-powerpoint',
        'application/json',
    }
)
_DOCUMENT_PREFIXES = (
    'text/',
    'application/vnd.openxmlformats-officedocument.',
    'application/vnd.oasis.opendocument.',
)


def clean_name(value: str | None, what: str = 'name') -> str:
    """A folder / file name: trimmed, NFC, no path separators or control characters (400 otherwise)."""
    name = unicodedata.normalize('NFC', (value or '').strip())
    if not name or name in ('.', '..'):
        raise ClientException(detail=f'{what} is required')
    if len(name) > MAX_NAME:
        raise ClientException(detail=f'{what} is longer than {MAX_NAME} characters')
    if any(c in '/\\' or unicodedata.category(c) in ('Cc', 'Cf') for c in name):
        raise ClientException(
            detail=f'{what} must not contain / \\ or control characters'
        )
    return name


def clean_color(value: str | None) -> str | None:
    """``#rrggbb`` or a palette token (``blue``, ``brand-1``); empty = no color."""
    color = (value or '').strip()
    if not color:
        return None
    if not _COLOR.match(color):
        raise ClientException(detail='color must be #rrggbb or a palette name')
    return color


def split_ext(name: str) -> tuple[str, str | None]:
    """``('report', 'pdf')`` for ``report.pdf``; ``None`` when there is no usable extension."""
    stem, dot, ext = name.rpartition('.')
    ext = ext.lower()
    if not dot or not stem or not _EXT.match(ext):
        return name, None
    return stem, ext


def numbered(name: str, n: int) -> str:
    """``report (2).pdf`` — the *keep both* name (File-0300)."""
    stem, ext = split_ext(name)
    base = f'{stem} ({n})'
    if ext:
        base = f'{base}.{ext}'
    if len(base) > MAX_NAME:
        cut = len(base) - MAX_NAME
        stem = stem[:-cut] if cut < len(stem) else stem[:1]
        base = f'{stem} ({n})' + (f'.{ext}' if ext else '')
    return base


def free_name(name: str, taken: set[str]) -> str:
    """``name`` or the first ``name (n)`` not in ``taken`` (lower-case names of the folder)."""
    if name.lower() not in taken:
        return name
    n = 1
    while True:
        candidate = numbered(name, n)
        if candidate.lower() not in taken:
            return candidate
        n += 1


def mime_of(name: str, declared: str | None = None) -> str:
    """Type from the extension, else the client's (when well-formed), else ``application/octet-stream``."""
    guessed, _ = mimetypes.guess_type(name, strict=False)
    if guessed:
        return guessed
    value = (declared or '').split(';', 1)[0].strip().lower()
    return value if _MIME.match(value) else 'application/octet-stream'


def file_type(kind: str, mime: str | None) -> FileType:
    """Quick tab of a node: All · Documents · Images · Videos · Others (UI §8)."""
    if kind == 'folder':
        return 'folder'
    mime = (mime or '').lower()
    if mime.startswith('image/'):
        return 'image'
    if mime.startswith('video/'):
        return 'video'
    if mime.startswith('audio/'):
        return 'audio'
    if mime in _DOCUMENT_EXACT or mime.startswith(_DOCUMENT_PREFIXES):
        return 'document'
    return 'other'


def type_patterns(file_type_: FileType) -> tuple[list[str], list[str]]:
    """``(exact mimes, mime prefixes)`` of a type (search filter); ``other`` = none of the others."""
    if file_type_ in ('image', 'video', 'audio'):
        return [], [f'{file_type_}/']
    if file_type_ == 'document':
        return sorted(_DOCUMENT_EXACT), list(_DOCUMENT_PREFIXES)
    return [], []


def inline_allowed(mime: str | None) -> bool:
    """Safe to show in the browser: images (not SVG), PDF, video, audio, plain text / Markdown / CSV."""
    mime = (mime or '').split(';', 1)[0].strip().lower()
    return mime in _INLINE_EXACT or mime.startswith(_INLINE_PREFIXES)


def viewer_kind(mime: str | None) -> ViewerKind:
    """What the viewer renders for a type (the URL may be a generated rendition, ``_uploads.preview``)."""
    mime = (mime or '').split(';', 1)[0].strip().lower()
    if mime.startswith('image/') and mime != 'image/svg+xml':
        return 'image'
    if mime == 'application/pdf':
        return 'pdf'
    if mime.startswith('video/'):
        return 'video'
    if mime.startswith('audio/'):
        return 'audio'
    if mime in ('text/plain', 'text/markdown', 'text/csv'):
        return 'text'
    return 'none'


def content_disposition(filename: str, *, inline: bool) -> str:
    """RFC 6266 header with an ASCII fallback and the UTF-8 name (``filename*``)."""
    ascii_name = (
        unicodedata.normalize('NFKD', filename).encode('ascii', 'ignore').decode()
    )
    ascii_name = (
        ''.join(c for c in ascii_name if c.isprintable() and c not in '"\\;')
        or 'download'
    )
    kind = 'inline' if inline else 'attachment'
    return f'{kind}; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(filename, safe="")}'


_WORD = re.compile(r'\w+')
MAX_QUERY_TERMS = 8
SNIPPET_START, SNIPPET_STOP = '\x02', '\x03'
"""Markers of the matched words in search snippets (never in indexed text: control characters are removed)."""


def prefix_tsquery(q: str | None) -> str | None:
    """``'invoice':* & 'acme':*`` for ``invoice acme`` — every word, as a prefix (type-ahead), quoted (no tsquery
    syntax from users); ``None`` when ``q`` has no word."""
    terms = [t.lower() for t in _WORD.findall(q or '')][:MAX_QUERY_TERMS]
    return ' & '.join(f"'{t}':*" for t in terms) if terms else None


def like_pattern(q: str) -> str:
    """``%q%`` with the LIKE wildcards of ``q`` escaped (use with ``escape='\\'``)."""
    escaped = q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return f'%{escaped}%'
