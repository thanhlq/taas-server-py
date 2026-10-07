"""Compact HMAC-signed tokens (media file URLs, site preview links): ``<payload b64url>.<sig b64url>``."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + '=' * (-len(data) % 4))


def _secret(secret: str | None) -> bytes:
    if secret:
        return secret.encode()
    from foundation.config import get_settings

    return str(get_settings().app.SECRET_KEY).encode()


def sign_token(payload: dict[str, Any], *, purpose: str, secret: str | None = None) -> str:
    """Sign ``payload`` (must contain ``exp``, epoch seconds) for one ``purpose`` (domain separation)."""
    body = _b64(json.dumps(payload, separators=(',', ':'), sort_keys=True).encode())
    mac = hmac.new(_secret(secret), f'{purpose}.{body}'.encode(), hashlib.sha256).digest()
    return f'{body}.{_b64(mac)}'


def verify_token(token: str, *, purpose: str, secret: str | None = None, now: float | None = None) -> dict[str, Any] | None:
    """The payload of a valid, unexpired token, else ``None``."""
    try:
        body, sig = token.split('.', 1)
        expected = hmac.new(_secret(secret), f'{purpose}.{body}'.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _unb64(sig)):
            return None
        payload = json.loads(_unb64(body))
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or float(payload.get('exp', 0)) < (now if now is not None else time.time()):
        return None
    return payload
