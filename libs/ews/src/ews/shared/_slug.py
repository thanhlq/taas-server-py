"""URL slugs of every app (sites, pages, blogs, posts, knowledge spaces, CRM accounts …) — Blog-0106.

One rule for the server and the web (``@taas/pages/lib/slug``): NFKD, letters that NFKD does not decompose
transliterated (``TRANSLITERATIONS``), combining marks and other non-ASCII characters dropped, lower case, runs
of anything but ``a-z0-9`` → one hyphen, trimmed, cut at ``max_len`` without a trailing hyphen. A text without
Latin letters or digits (Japanese, Arabic …) gives ``''``: the caller picks its fallback (``post``, ``page`` …).
"""

from __future__ import annotations

import re
import unicodedata

TRANSLITERATIONS: dict[str, str] = {
    'đ': 'd',
    'Đ': 'D',
    'ð': 'd',
    'Ð': 'D',
    'ß': 'ss',
    'ẞ': 'SS',
    'æ': 'ae',
    'Æ': 'AE',
    'ø': 'o',
    'Ø': 'O',
    'ł': 'l',
    'Ł': 'L',
    'œ': 'oe',
    'Œ': 'OE',
    'þ': 'th',
    'Þ': 'TH',
    'ı': 'i',
    'ħ': 'h',
    'Ħ': 'H',
    'ŧ': 't',
    'Ŧ': 'T',
    'ŋ': 'ng',
    'Ŋ': 'NG',
    'ĸ': 'k',
}
"""Latin letters NFKD leaves whole (no base letter + combining mark), mapped to their usual ASCII spelling."""

_TABLE = str.maketrans(TRANSLITERATIONS)
_NON_SLUG = re.compile(r'[^a-z0-9]+')

SLUG_MAX = 80
"""Default (and the posts / pages) maximum length."""


def slugify(text: str, max_len: int = SLUG_MAX) -> str:
    """``'Getting started with Đà Nẵng'`` → ``'getting-started-with-da-nang'`` (≤ ``max_len``)."""
    decomposed = unicodedata.normalize('NFKD', text or '').translate(_TABLE)
    ascii_text = decomposed.encode('ascii', 'ignore').decode()
    slug = _NON_SLUG.sub('-', ascii_text.lower()).strip('-')
    return slug[:max_len].strip('-')
