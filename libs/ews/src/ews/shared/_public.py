"""Helpers of public (sign-in free) endpoints: unguessable ids and tokens, token hashes, the caller's IP hash for rate
limits (SHA-256 of IP + a daily salt derived from the server secret — the IP itself is never stored)."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import string
from datetime import UTC, datetime

from foundation.http.context_state import get_request_context

from ._signing import _secret

_BASE62 = string.digits + string.ascii_letters


def random_id(bits: int = 128) -> str:
    """A random base62 id of at least ``bits`` bits (public form ids: 128 → 22 characters)."""
    length = -(-bits * 1000 // 5954)  # log2(62) ≈ 5.954
    return ''.join(secrets.choice(_BASE62) for _ in range(length))


def random_token(bits: int = 256) -> str:
    """A URL-safe secret token (tracking links); store only ``token_hash``."""
    return secrets.token_urlsafe(bits // 8)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def client_ip() -> str | None:
    """The caller's address of the current request (the server resolves trusted proxy headers)."""
    ctx = get_request_context()
    client = getattr(ctx.req, 'client', None) if ctx is not None else None
    return getattr(client, 'host', None) if client is not None else None


def client_ip_hash(ip: str | None = None, *, day: str | None = None) -> str | None:
    """HMAC-SHA-256 of the IP with a salt that changes every day (UTC); ``None`` without an address."""
    ip = ip or client_ip()
    if not ip:
        return None
    salt = day or datetime.now(UTC).date().isoformat()
    return hmac.new(
        _secret(None), f'ip:{salt}:{ip}'.encode(), hashlib.sha256
    ).hexdigest()
