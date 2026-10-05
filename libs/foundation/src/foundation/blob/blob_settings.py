"""Blob storage settings (contract §6). Provider-specific keys live in the adapter libs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Final

from foundation.utils.env_utils import get_env

from .blob_errors import BlobValidationError
from .blob_types import DEFAULT_PRESIGN_EXPIRES, MAX_PRESIGN_EXPIRES, BlobProvider

PROVIDER_ALIASES: Final[dict[str, BlobProvider]] = {
    's3': 's3',
    'gcp': 'gcp',
    'gcs': 'gcp',
    'azure': 'azure',
    'memory': 'memory',
}

_PREFIX_PATTERN: Final[re.Pattern[str]] = re.compile(r'^([a-z0-9][a-z0-9-]*)?$')
TENANT_CODE_LENGTH: Final[int] = 8
MAX_BUCKET_LENGTH: Final[int] = 63


def normalize_provider(value: str) -> BlobProvider:
    """`s3` | `gcp` (alias `gcs`) | `azure` | `memory` (case-insensitive), else `BlobValidationError`."""
    provider = PROVIDER_ALIASES.get(value.strip().lower())
    if provider is None:
        raise BlobValidationError(
            f'Invalid BLOB_STORAGE_PROVIDER {value!r}: expected s3 | gcp (alias gcs) | azure | memory'
        )
    return provider


@dataclass
class BlobSettings:
    """Blob service settings, read from the environment (one shared `.env` for Python and Node)."""

    BLOB_STORAGE_PROVIDER: str = field(
        default_factory=get_env('BLOB_STORAGE_PROVIDER', 's3')
    )
    """`s3` (AWS S3, Cloudflare R2, RustFS) | `gcp` (alias `gcs`) | `azure` | `memory`; normalised (`gcs` → `gcp`)."""

    BLOB_BUCKET_PREFIX: str = field(
        default_factory=get_env('BLOB_BUCKET_PREFIX', 'taas-')
    )
    """Tenant bucket name = prefix + `tenant_code`. GCS names are global: use a deployment-specific prefix."""

    BLOB_PRESIGN_EXPIRES: int = field(
        default_factory=get_env('BLOB_PRESIGN_EXPIRES', DEFAULT_PRESIGN_EXPIRES)
    )
    """Default presigned URL lifetime in seconds (1..604800)."""

    def __post_init__(self) -> None:
        self.BLOB_STORAGE_PROVIDER = normalize_provider(self.BLOB_STORAGE_PROVIDER)  # pyright: ignore[reportConstantRedefinition]
        if not _PREFIX_PATTERN.fullmatch(self.BLOB_BUCKET_PREFIX) or (
            len(self.BLOB_BUCKET_PREFIX) + TENANT_CODE_LENGTH > MAX_BUCKET_LENGTH
        ):
            raise BlobValidationError(
                f'Invalid BLOB_BUCKET_PREFIX {self.BLOB_BUCKET_PREFIX!r}: lower-case letters, digits and "-", '
                f'starting with a letter or digit, at most {MAX_BUCKET_LENGTH - TENANT_CODE_LENGTH} characters'
            )
        if not 1 <= self.BLOB_PRESIGN_EXPIRES <= MAX_PRESIGN_EXPIRES:
            raise BlobValidationError(
                f'Invalid BLOB_PRESIGN_EXPIRES {self.BLOB_PRESIGN_EXPIRES}: expected 1..{MAX_PRESIGN_EXPIRES}'
            )

    @property
    def provider(self) -> BlobProvider:
        """The normalised provider."""
        return normalize_provider(self.BLOB_STORAGE_PROVIDER)


@lru_cache(maxsize=1)
def get_blob_settings() -> BlobSettings:
    """Process-wide blob settings (read once from the environment)."""
    return BlobSettings()
