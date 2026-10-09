"""File Manager limits, delivery and pipeline (``.env.example`` §11, ``FILES_*``)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

_MB = 1024 * 1024

type PipelineRunner = Literal['api', 'worker', 'off']


def _int(key: str, default: int) -> int:
    value = os.environ.get(key)
    return int(value) if value not in (None, '') else default


def _clamp(value: int, low: int, high: int) -> int:
    return min(max(value, low), high)


@dataclass(frozen=True, slots=True)
class FilesSettings:
    max_upload_bytes: int = 200 * _MB
    """Largest file (API multipart and direct uploads) — File-0300 size limit."""
    url_ttl_seconds: int = 300
    """Lifetime of download URLs (attachments) and of every URL of a *confidential* drive: 1–5 min (Sto-0200)."""
    view_ttl_seconds: int = 24 * 3600
    """Lifetime of view URLs (thumbnails, preview renditions, inline originals of safe types) on *standard* drives:
    1–24 h, rounded to a fixed window and cached (File-0500, ADR-9)."""
    upload_ttl_seconds: int = 3600
    """Lifetime of an upload ticket (direct upload URL + completion token)."""
    delivery: Literal['proxy', 'presigned'] = 'proxy'
    """``proxy``: signed EWS URLs stream the bytes and receive direct uploads (any storage, internal too);
    ``presigned``: provider-signed GET / PUT URLs (storage reachable by browsers, CORS on the bucket)."""
    public_base_url: str = 'http://localhost:8191'
    """Origin of the EWS API as seen by browsers (``proxy`` URLs)."""
    trash_days: int = 30
    """Trash retention before ``purge_expired`` deletes for good (File-0306)."""
    pipeline: PipelineRunner = 'api'
    """Who runs the processing pipeline (previews, index, retention): ``api`` (a background task of each API
    process), ``worker`` (``ews_worker``), ``off`` (nobody: tests call ``run_pipeline``)."""
    pipeline_interval_seconds: int = 3
    """Pause between two polls of the queue when it is empty."""
    pipeline_batch: int = 8
    """Versions claimed per poll."""
    pipeline_max_bytes: int = 100 * _MB
    """Larger files get no preview / index (``none``)."""
    index_max_chars: int = 200_000
    """Characters of extracted text kept per file (search index, AI context)."""

    @staticmethod
    def from_env() -> FilesSettings:
        delivery = (os.environ.get('FILES_DELIVERY') or 'proxy').strip().lower()
        if delivery not in ('proxy', 'presigned'):
            raise ValueError('FILES_DELIVERY must be proxy or presigned')
        pipeline = (os.environ.get('FILES_PIPELINE') or 'api').strip().lower()
        if pipeline not in ('api', 'worker', 'off'):
            raise ValueError('FILES_PIPELINE must be api, worker or off')
        base = (
            os.environ.get('FILES_PUBLIC_BASE_URL')
            or os.environ.get('MEDIA_PUBLIC_BASE_URL')
            or 'http://localhost:8191'
        )
        return FilesSettings(
            max_upload_bytes=_int('FILES_MAX_UPLOAD_MB', 200) * _MB,
            url_ttl_seconds=_clamp(_int('FILES_URL_TTL_SECONDS', 300), 60, 300),
            view_ttl_seconds=_clamp(_int('FILES_VIEW_URL_TTL_HOURS', 24), 1, 24) * 3600,
            upload_ttl_seconds=_clamp(
                _int('FILES_UPLOAD_TTL_SECONDS', 3600), 300, 6 * 3600
            ),
            delivery=delivery,  # type: ignore[arg-type]
            public_base_url=base.rstrip('/'),
            trash_days=max(_int('FILES_TRASH_DAYS', 30), 1),
            pipeline=pipeline,  # type: ignore[arg-type]
            pipeline_interval_seconds=_clamp(
                _int('FILES_PIPELINE_INTERVAL_SECONDS', 3), 1, 300
            ),
            pipeline_batch=_clamp(_int('FILES_PIPELINE_BATCH', 8), 1, 100),
            pipeline_max_bytes=max(_int('FILES_PIPELINE_MAX_MB', 100), 1) * _MB,
            index_max_chars=_clamp(
                _int('FILES_INDEX_MAX_CHARS', 200_000), 1_000, 1_000_000
            ),
        )


@lru_cache(maxsize=1)
def files_settings() -> FilesSettings:
    return FilesSettings.from_env()
