"""SEO fields of a public page or post (Site-0700, Blog-0300): validated, trimmed, unknown keys dropped."""

from __future__ import annotations

import re
from typing import Any

from foundation.exceptions import ClientException

SEO_TITLE_MAX = 120
SEO_DESCRIPTION_MAX = 320
_ASSET = re.compile(r'^asset:[0-9a-fA-F-]{36}$')


def clean_seo(raw: dict[str, Any] | None) -> dict[str, Any]:
    """``title`` (≤ 120), ``description`` (≤ 320), ``canonical`` (absolute http(s) URL), ``og_image``
    (``asset:<id>``); empty values are dropped. 400 on an invalid value."""
    out: dict[str, Any] = {}
    raw = raw or {}
    for key, limit in (('title', SEO_TITLE_MAX), ('description', SEO_DESCRIPTION_MAX)):
        value = raw.get(key)
        if value:
            if not isinstance(value, str) or len(value) > limit:
                raise ClientException(
                    detail=f'seo.{key} must be at most {limit} characters'
                )
            out[key] = value.strip()
    canonical = raw.get('canonical')
    if canonical:
        if (
            not isinstance(canonical, str)
            or not canonical.startswith(('https://', 'http://'))
            or len(canonical) > 1024
        ):
            raise ClientException(detail='seo.canonical must be an absolute URL')
        out['canonical'] = canonical
    og = raw.get('og_image')
    if og:
        if not isinstance(og, str) or not _ASSET.match(og):
            raise ClientException(detail='seo.og_image must be asset:<id>')
        out['og_image'] = og
    return out
