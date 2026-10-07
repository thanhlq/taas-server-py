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
class MediaSettings:
    """Media library limits and delivery (``.env`` §Media library)."""

    max_image_bytes: int = 20 * _MB
    max_video_bytes: int = 200 * _MB
    max_audio_bytes: int = 50 * _MB
    quota_bytes: int = 10 * 1024 * _MB
    """Storage quota per tenant (originals + variants + trash); 0 = unlimited (Site-0004)."""
    variant_widths: tuple[int, ...] = (320, 640, 1280, 1920)
    avif: bool = True
    delivery: Literal['proxy', 'presigned'] = 'proxy'
    """``proxy``: signed EWS URLs stream the bytes (works with private / internal storage);
    ``presigned``: signed storage URLs (S3 / R2 / GCS / Azure reachable by browsers)."""
    public_base_url: str = 'http://localhost:8191'
    """Origin of the EWS API as seen by browsers (signed ``/api/v1/media/files/…`` URLs)."""

    @property
    def max_upload_bytes(self) -> int:
        return max(self.max_image_bytes, self.max_video_bytes, self.max_audio_bytes)

    def max_bytes(self, kind: str) -> int:
        return {'image': self.max_image_bytes, 'video': self.max_video_bytes}.get(kind, self.max_audio_bytes)

    @staticmethod
    def from_env() -> MediaSettings:
        widths = os.environ.get('MEDIA_VARIANT_WIDTHS') or '320,640,1280,1920'
        delivery = (os.environ.get('MEDIA_DELIVERY') or 'proxy').strip().lower()
        if delivery not in ('proxy', 'presigned'):
            raise ValueError('MEDIA_DELIVERY must be proxy or presigned')
        return MediaSettings(
            max_image_bytes=_int('MEDIA_MAX_IMAGE_MB', 20) * _MB,
            max_video_bytes=_int('MEDIA_MAX_VIDEO_MB', 200) * _MB,
            max_audio_bytes=_int('MEDIA_MAX_AUDIO_MB', 50) * _MB,
            quota_bytes=_int('MEDIA_QUOTA_GB', 10) * 1024 * _MB,
            variant_widths=tuple(sorted({int(w) for w in widths.split(',') if w.strip()})),
            avif=(os.environ.get('MEDIA_AVIF') or 'true').strip().lower() in ('1', 'true', 'yes'),
            delivery=delivery,  # type: ignore[arg-type]
            public_base_url=(os.environ.get('MEDIA_PUBLIC_BASE_URL') or 'http://localhost:8191').rstrip('/'),
        )


@lru_cache(maxsize=1)
def media_settings() -> MediaSettings:
    return MediaSettings.from_env()
