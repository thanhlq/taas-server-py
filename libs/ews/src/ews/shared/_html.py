"""Rich text (HTML) written in the web editors — comments, descriptions: sanitized on the server with ``nh3``
(Rust *ammonia*), plain text for search / e-mails, and the users it mentions (``<span data-type="mention"
data-id="…">``, the Tiptap mention node)."""

from __future__ import annotations

import html
import re

import nh3

MAX_HTML = 100_000
_TAGS = {
    'p',
    'br',
    'strong',
    'b',
    'em',
    'i',
    'u',
    's',
    'code',
    'pre',
    'blockquote',
    'ul',
    'ol',
    'li',
    'a',
    'span',
    'h1',
    'h2',
    'h3',
    'h4',
    'hr',
}
_ATTRIBUTES = {
    'a': {'href', 'title'},
    'span': {'data-type', 'data-id', 'data-label', 'class'},
    'code': {'class'},
    'ol': {'start'},
}
_MENTION = re.compile(r'<span\b[^>]*\bdata-type="mention"[^>]*>', re.IGNORECASE)
_DATA_ID = re.compile(r'\bdata-id="([^"]+)"', re.IGNORECASE)
_BLOCK_END = re.compile(r'</(p|li|h[1-4]|blockquote|pre)>|<br\s*/?>', re.IGNORECASE)
_TAG = re.compile(r'<[^>]+>')


def sanitize_html(value: str | None) -> str:
    """Allowed tags and attributes only; links ``http(s)`` / ``mailto`` with ``rel="noopener noreferrer"``."""
    if not value:
        return ''
    return nh3.clean(
        value[:MAX_HTML],
        tags=_TAGS,
        attributes=_ATTRIBUTES,
        url_schemes={'http', 'https', 'mailto'},
        link_rel='noopener noreferrer',
    )


def html_to_text(value: str | None) -> str:
    """Plain text of (sanitized) HTML: blocks become lines, entities decoded, spaces collapsed per line."""
    if not value:
        return ''
    text = _TAG.sub('', _BLOCK_END.sub('\n', value))
    lines = [' '.join(html.unescape(line).split()) for line in text.splitlines()]
    return '\n'.join(line for line in lines if line)


def mentioned_users(value: str | None) -> list[str]:
    """User refs (id or e-mail) of the mention chips, in order, without duplicates."""
    out: list[str] = []
    for tag in _MENTION.findall(value or ''):
        found = _DATA_ID.search(tag)
        if found:
            ref = html.unescape(found.group(1)).strip()
            if ref and ref not in out:
                out.append(ref)
    return out
