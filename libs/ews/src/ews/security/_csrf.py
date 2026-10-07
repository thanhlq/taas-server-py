"""Cross-site request forgery guard of the cookie-authenticated EWS routes (taas-specs/platform/security).

A state-changing request (``POST`` / ``PUT`` / ``PATCH`` / ``DELETE``) that is authenticated by cookies (the IAM
session or the development sign-in cookie) must come from an allowed web origin: its ``Origin`` header is one of
``ALLOWED_CORS_ORIGINS`` or the API's own origin. Bearer tokens and server-to-server keys carry no CSRF risk.
Same rule as the IAM admin API (taas-server-js ``iam-http`` ``requireCsrf``).
"""

from __future__ import annotations

import json
import os
from collections.abc import Collection, Mapping
from functools import lru_cache

from foundation.exceptions import PermissionDeniedException

SAFE_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS'})


def check_origin(method: str, headers: Mapping[str, str], own_origin: str, allowed: Collection[str]) -> None:
    """403 unless a cookie-authenticated write comes from an allowed origin (``headers`` keys lower-case)."""
    if method.upper() in SAFE_METHODS or not headers.get('cookie'):
        return
    if (headers.get('authorization') or '').lower().startswith('bearer '):
        return
    origin = (headers.get('origin') or '').rstrip('/')
    if '*' in allowed and origin:
        return
    if not origin or (origin not in allowed and origin != own_origin.rstrip('/')):
        raise PermissionDeniedException(detail='cross-site request rejected: origin not allowed')


@lru_cache(maxsize=1)
def allowed_web_origins() -> frozenset[str]:
    """``ALLOWED_CORS_ORIGINS`` (JSON list or comma-separated), the web apps allowed to call the API."""
    raw = (os.environ.get('ALLOWED_CORS_ORIGINS') or '').strip()
    if not raw:
        return frozenset()
    try:
        values = json.loads(raw) if raw.startswith('[') else raw.split(',')
    except ValueError:
        values = raw.strip('[]').split(',')
    return frozenset(str(v).strip().strip('"\'').rstrip('/') for v in values if str(v).strip())
