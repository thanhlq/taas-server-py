"""S3 compatible settings (contract §6): AWS S3, Cloudflare R2, RustFS / MinIO."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from foundation.utils.env_utils import get_env


def _region_from_env() -> str:
    return os.getenv('AWS_REGION') or os.getenv('AWS_DEFAULT_REGION') or 'us-east-1'


def _force_path_style_from_env() -> bool | None:
    raw = os.getenv('AWS_S3_FORCE_PATH_STYLE')
    if raw is None or not raw.strip():
        return None
    return get_env('AWS_S3_FORCE_PATH_STYLE', False)()


@dataclass
class S3BlobSettings:
    """Read from the environment; empty strings mean "not set"."""

    AWS_ENDPOINT_URL: str = field(default_factory=get_env('AWS_ENDPOINT_URL', ''))
    """S3 compatible endpoint (RustFS `http://localhost:19000`, R2 `https://<account>.r2.cloudflarestorage.com`); empty = AWS."""

    AWS_REGION: str = field(default_factory=_region_from_env)
    """`AWS_REGION`, else `AWS_DEFAULT_REGION`, else `us-east-1` (R2: `auto`)."""

    AWS_ACCESS_KEY_ID: str = field(default_factory=get_env('AWS_ACCESS_KEY_ID', ''))
    AWS_SECRET_ACCESS_KEY: str = field(
        default_factory=get_env('AWS_SECRET_ACCESS_KEY', '')
    )
    """Static credentials; both empty = the SDK default credential chain."""

    AWS_S3_FORCE_PATH_STYLE: bool | None = field(
        default_factory=_force_path_style_from_env
    )
    """Path-style URLs; `None` (unset) = `True` when an endpoint is set."""

    @property
    def endpoint_url(self) -> str | None:
        return self.AWS_ENDPOINT_URL.strip() or None

    @property
    def force_path_style(self) -> bool:
        if self.AWS_S3_FORCE_PATH_STYLE is not None:
            return self.AWS_S3_FORCE_PATH_STYLE
        return self.endpoint_url is not None
