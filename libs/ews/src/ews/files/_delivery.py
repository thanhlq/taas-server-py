"""Signed delivery of file bytes (File-0500 … File-0505, decisions ADR-9 / ADR-10).

The permission check happens when a URL is handed out; the URL itself is a bearer token, so its lifetime follows the
drive's **sensitivity**:

| Drive | View URLs (thumbnails, previews, inline originals) | Download URLs (attachments) |
| --- | --- | --- |
| ``standard`` | ``FILES_VIEW_URL_TTL_HOURS`` (24 h), HTTP-cacheable (``private, max-age, immutable``) | ``FILES_URL_TTL_SECONDS`` (≤ 5 min), ``no-store`` |
| ``confidential`` | ``FILES_URL_TTL_SECONDS``, ``no-store`` | same |

- Expiries are **rounded** to a ``ttl / 4`` grid and signed URLs are **cached** (``ews.shared.SignedUrlCache``): the
  same URL for every caller within a window — no re-signing, browser and CDN cache hits. Object keys are immutable
  (one per version / variant), so a cached response is never stale.
- **Revocation** (proxy delivery): a token carries the node id and the drive's ``url_epoch``; ``GET /content/{token}``
  answers 404 when the item is trashed / purged, the drive deleted or the epoch bumped (*Revoke links*, member
  removed, sensitivity changed). The state is cached ≤ 30 s per process. Provider-signed URLs (``presigned``) cannot be
  revoked before they expire (rotate the storage keys as the emergency lever).
- Responses: ``ETag`` from the immutable key (``If-None-Match`` → 304 without reading storage), single ``Range``
  requests (video / audio seeking) → 206.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from foundation.blob import BlobPresignOptions
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import NotFoundException
from sqlalchemy import text

from ews.shared import (
    SignedUrlCache,
    raw_response,
    rounded_expiry,
    sign_token,
    verify_token,
)

from ._rules import content_disposition
from ._settings import FilesSettings, files_settings
from ._storage import store_for

CONTENT_PURPOSE = 'files.content'
SENSITIVITIES = ('standard', 'confidential')
type Sensitivity = Literal['standard', 'confidential']

LINK_STATE_SECONDS = 30.0
"""How long a process trusts its cached state of a link (revocation delay of proxy URLs)."""

_URLS = SignedUrlCache('files.url')


def sensitivity_of(settings: dict[str, Any] | None) -> Sensitivity:
    value = (settings or {}).get('sensitivity')
    return 'confidential' if value == 'confidential' else 'standard'


def epoch_of(settings: dict[str, Any] | None) -> int:
    try:
        return int((settings or {}).get('url_epoch') or 0)
    except TypeError, ValueError:
        return 0


@dataclass(frozen=True, slots=True)
class UrlPolicy:
    ttl: int
    cacheable: bool
    """HTTP-cacheable response (``private, max-age, immutable``); otherwise ``private, no-store``."""


def url_policy(
    drive_settings: dict[str, Any] | None,
    *,
    view: bool,
    settings: FilesSettings | None = None,
) -> UrlPolicy:
    settings = settings or files_settings()
    if view and sensitivity_of(drive_settings) == 'standard':
        return UrlPolicy(settings.view_ttl_seconds, True)
    return UrlPolicy(settings.url_ttl_seconds, False)


async def signed_url(
    tenant_id: UUID,
    drive_settings: dict[str, Any] | None,
    node_id: UUID,
    key: str,
    mime: str,
    filename: str,
    *,
    inline: bool,
    view: bool,
    settings: FilesSettings | None = None,
    now: float | None = None,
) -> tuple[str, int]:
    """``(url, exp)`` for an object the caller was allowed to read (cached per window, see the module doc)."""
    settings = settings or files_settings()
    policy = url_policy(drive_settings, view=view, settings=settings)
    current = time.time() if now is None else now
    exp = rounded_expiry(policy.ttl, current)
    epoch = epoch_of(drive_settings)
    if settings.delivery == 'presigned':

        async def presign() -> str:
            store = await store_for(tenant_id)
            return await store.presign(
                key,
                BlobPresignOptions(
                    method='GET',
                    expires_in=max(exp - int(current), 1),
                    download_name=None if inline else filename,
                ),
            )

        cache_key = f'p:{tenant_id}:{key}:{int(inline)}:{"" if inline else filename}'
        return await _URLS.get_or_sign(
            cache_key, exp, presign, shared=True, now=current
        ), exp
    payload = {
        't': str(tenant_id),
        'k': key,
        'm': mime,
        'f': filename,
        'i': inline,
        'n': str(node_id),
        'e': epoch,
        'c': policy.cacheable,
        'exp': exp,
    }

    async def sign() -> str:
        token = sign_token(payload, purpose=CONTENT_PURPOSE)
        return f'{settings.public_base_url}/api/v1/files/content/{token}'

    cache_key = f'x:{key}:{int(inline)}:{filename}:{epoch}:{int(policy.cacheable)}'
    return await _URLS.get_or_sign(cache_key, exp, sign, now=current), exp


def forget_urls() -> None:
    """Drop this process' cached URLs (tests; a new epoch changes the cache key anyway)."""
    _URLS.clear()


# --- revocation state (proxy delivery) ------------------------------------------------------------


@dataclass(slots=True)
class _LinkState:
    live: bool
    epoch: int
    until: float


_STATES: dict[str, _LinkState] = {}
_MAX_STATES = 50_000


def forget_link_states() -> None:
    """Forget the cached link states of this process (after a revocation, so it applies here at once)."""
    _STATES.clear()


async def link_alive(session: DBAsyncScopedSession, node_id: str, epoch: int) -> bool:
    """The item is live, its drive too, and the token's epoch is the drive's current one."""
    now = time.monotonic()
    state = _STATES.get(node_id)
    if state is None or state.until < now:
        row = (
            await session.execute(
                text(
                    'select (n.trashed_at is null and n.deleted_at is null and d.deleted_at is null) as live, '
                    "coalesce((d.settings->>'url_epoch')::int, 0) as epoch "
                    'from taas_file_nodes n join taas_file_drives d on d.id = n.drive_id where n.id = :n'
                ),
                {'n': node_id},
            )
        ).first()
        if len(_STATES) >= _MAX_STATES:
            _STATES.clear()
        state = _LinkState(
            live=bool(row and row.live),
            epoch=int(row.epoch) if row else -1,
            until=now + LINK_STATE_SECONDS,
        )
        _STATES[node_id] = state
    return state.live and state.epoch == epoch


# --- responses ------------------------------------------------------------------------------------


def etag_of(key: str) -> str:
    """Strong ETag of an immutable object key (no storage call needed)."""
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def content_headers(
    mime: str,
    filename: str,
    *,
    inline: bool,
    cacheable: bool = False,
    exp: int | None = None,
    etag: str | None = None,
    now: float | None = None,
) -> dict[str, str]:
    """Headers of a proxied file: risky types are always attachments, never sniffed (Sto-0202)."""
    current = time.time() if now is None else now
    max_age = max(int((exp or 0) - current), 0)
    headers = {
        'content-disposition': content_disposition(filename, inline=inline),
        'x-content-type-options': 'nosniff',
        'cache-control': f'private, max-age={max_age}, immutable'
        if cacheable and max_age
        else 'private, no-store',
        'cross-origin-resource-policy': 'cross-origin',
        'accept-ranges': 'bytes',
    }
    if inline and mime != 'application/pdf':
        headers['content-security-policy'] = (
            "default-src 'none'; img-src 'self' data:; media-src 'self'; style-src 'unsafe-inline'; sandbox"
        )
    if etag:
        headers['etag'] = f'"{etag}"'
    return headers


def parse_range(
    value: str | None, size: int
) -> tuple[int, int] | None | Literal[False]:
    """``(start, end)`` (inclusive) of a single ``bytes=`` range; ``None`` = no / ignored range; ``False`` = not
    satisfiable (416)."""
    if not value or not value.startswith('bytes=') or ',' in value:
        return None
    start_text, _, end_text = value[6:].strip().partition('-')
    try:
        if start_text == '':
            suffix = int(end_text)
            if suffix <= 0:
                return False
            return max(size - suffix, 0), size - 1
        start = int(start_text)
        end = int(end_text) if end_text else size - 1
    except ValueError:
        return None
    if start >= size or end < start:
        return False
    return start, min(end, size - 1)


async def content_response(
    session: DBAsyncScopedSession, token: str, request: Any
) -> Any:
    """``GET /content/{token}``: bytes behind a signed proxy URL (no session; the token is the authorization)."""
    claims = verify_token(token, purpose=CONTENT_PURPOSE)
    if claims is None:
        raise NotFoundException(detail='link expired or invalid')
    if 'n' in claims and not await link_alive(
        session, str(claims['n']), int(claims.get('e') or 0)
    ):
        raise NotFoundException(detail='link revoked')
    key: str = claims['k']
    mime: str = claims.get('m') or 'application/octet-stream'
    inline = bool(claims.get('i'))
    etag = etag_of(key)
    headers = content_headers(
        mime,
        claims['f'],
        inline=inline,
        cacheable=bool(claims.get('c')),
        exp=int(claims['exp']),
        etag=etag,
    )
    req_headers = getattr(request, 'headers', {}) or {}
    if_none_match = req_headers.get('if-none-match')
    if if_none_match and etag in if_none_match:
        return raw_response(
            b'', media_type=mime, status_code=304, headers=headers, request=request
        )
    blob = await (await store_for(claims['t'])).get(key)
    if blob is None:
        raise NotFoundException(detail='file not found')
    body = blob.body
    wanted = parse_range(req_headers.get('range'), len(body))
    if wanted is False:
        return raw_response(
            b'',
            media_type=mime,
            status_code=416,
            headers={**headers, 'content-range': f'bytes */{len(body)}'},
            request=request,
        )
    if wanted is not None:
        start, end = wanted
        return raw_response(
            body[start : end + 1],
            media_type=mime,
            status_code=206,
            headers={**headers, 'content-range': f'bytes {start}-{end}/{len(body)}'},
            request=request,
        )
    return raw_response(body, media_type=mime, headers=headers, request=request)
