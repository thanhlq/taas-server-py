"""File Manager limits and delivery (``.env.example`` §11, ``FILES_*``)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

_MB = 1024 * 1024


def _int(key: str, default: int) -> int:
    value = os.environ.get(key)
    return int(value) if value not in (None, '') else default


@dataclass(frozen=True, slots=True)
class FilesSettings:
    max_upload_bytes: int = 200 * _MB
    """Largest file (API multipart and direct uploads) — File-0300 size limit."""
    url_ttl_seconds: int = 300
    """Lifetime of download / preview URLs: 1–5 min (Sto-0200)."""
    upload_ttl_seconds: int = 3600
    """Lifetime of an upload ticket (direct upload URL + completion token)."""
    delivery: Literal['proxy', 'presigned'] = 'proxy'
    """``proxy``: signed EWS URLs stream the bytes and receive direct uploads (any storage, internal too);
    ``presigned``: provider-signed GET / PUT URLs (storage reachable by browsers, CORS on the bucket)."""
    public_base_url: str = 'http://localhost:8191'
    """Origin of the EWS API as seen by browsers (``proxy`` URLs)."""
    trash_days: int = 30
    """Trash retention before ``purge_expired`` deletes for good (File-0306)."""

    @staticmethod
    def from_env() -> FilesSettings:
        delivery = (os.environ.get('FILES_DELIVERY') or 'proxy').strip().lower()
        if delivery not in ('proxy', 'presigned'):
            raise ValueError('FILES_DELIVERY must be proxy or presigned')
        base = (
            os.environ.get('FILES_PUBLIC_BASE_URL')
            or os.environ.get('MEDIA_PUBLIC_BASE_URL')
            or 'http://localhost:8191'
        )
        return FilesSettings(
            max_upload_bytes=_int('FILES_MAX_UPLOAD_MB', 200) * _MB,
            url_ttl_seconds=min(max(_int('FILES_URL_TTL_SECONDS', 300), 60), 300),
            upload_ttl_seconds=min(
                max(_int('FILES_UPLOAD_TTL_SECONDS', 3600), 300), 6 * 3600
            ),
            delivery=delivery,  # type: ignore[arg-type]
            public_base_url=base.rstrip('/'),
            trash_days=max(_int('FILES_TRASH_DAYS', 30), 1),
        )


@lru_cache(maxsize=1)
def files_settings() -> FilesSettings:
    return FilesSettings.from_env()
