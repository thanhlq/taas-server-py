"""Content storage on top of the blob contract (taas-specs/platform/storage/storage-architecture-spec.md).

- **Private storage** per tenant, pooled (`STORAGE_PRIVATE_BUCKET` + `{tenantId}/`) or dedicated (one bucket per
  tenant), split into *kinds* (`uploads/`, `derived/`, `knowledge/`, `documents/`). Apps only call
  `StorageResolverT` — never build bucket names.
- **Public storage**: one shared bucket behind the CDN (`CDN_*`), content-hashed immutable keys
  `{tenantId}/{scope}/{sha256}.{ext}`; publishing copies private files there (`PublicStoreT`).
"""

from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Final, Literal

from .blob_errors import BlobValidationError
from .blob_interfaces import TenantBlobStoreT, TenantId

StorageKind = Literal['upload', 'derived', 'knowledge', 'document']
StorageMode = Literal['pooled', 'dedicated']

STORAGE_KIND_PREFIXES: Final[dict[StorageKind, str]] = {
    'upload': 'uploads/',
    'derived': 'derived/',
    'knowledge': 'knowledge/',
    'document': 'documents/',
}
"""Prefix of each kind below the tenant root (spec §2.2)."""

IMMUTABLE_CACHE: Final[str] = 'public, max-age=31536000, immutable'
_SCOPE_PATTERN: Final[re.Pattern[str]] = re.compile(r'^[a-z0-9][a-z0-9-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*$')
_EXT_PATTERN: Final[re.Pattern[str]] = re.compile(r'^[a-z0-9]{1,8}$')
_SHA256_PATTERN: Final[re.Pattern[str]] = re.compile(r'^[0-9a-f]{64}$')


def kind_key(kind: StorageKind, key: str) -> str:
    """`kind_key('upload', 'media/…')` → `uploads/media/…` (a key relative to the tenant root)."""
    return f'{STORAGE_KIND_PREFIXES[kind]}{key.lstrip("/")}'


@dataclass(frozen=True, slots=True, kw_only=True)
class StorageLocation:
    bucket: str
    prefix: str
    """Key prefix of the kind in `bucket` (`{tenantId}/uploads/` pooled, `uploads/` dedicated)."""
    region: str
    mode: StorageMode
    kms_key_id: str | None = None
    """Per-tenant key where the provider supports it (AWS SSE-KMS, GCS CMEK, Azure CMK); `None` on R2."""


class StorageResolverT(ABC):
    """Where a tenant's private files of one kind live (spec §2.3)."""

    @abstractmethod
    async def resolve(self, tenant_id: TenantId, kind: StorageKind) -> StorageLocation: ...

    @abstractmethod
    async def store(self, tenant_id: TenantId, kind: StorageKind) -> TenantBlobStoreT:
        """A store whose keys are relative to the kind prefix (`list` only sees that prefix)."""

    @abstractmethod
    async def root(self, tenant_id: TenantId) -> TenantBlobStoreT:
        """The tenant root: keys start with a kind prefix (`uploads/…`, `derived/…`); see `kind_key`.

        Every kind of a tenant lives in the same bucket, so files spanning kinds (an original in `uploads/` and its
        variants in `derived/`) can be stored with one key column each.
        """


@dataclass(frozen=True, slots=True, kw_only=True)
class PublicObject:
    key: str
    url: str
    created: bool
    """`False` when the object already existed (content-hashed keys are written once)."""


class PublicStoreT(ABC):
    """The shared public bucket behind the CDN (spec §3)."""

    @property
    @abstractmethod
    def enabled(self) -> bool:
        """`False` when no CDN is configured (publishing falls back to app-served files)."""

    @property
    @abstractmethod
    def base_url(self) -> str:
        """Public base URL (the media domain), without a trailing slash."""

    def key(self, tenant_id: TenantId, scope: str, sha256: str, ext: str) -> str:
        """`{tenantId}/{scope}/{sha256}.{ext}` — scope e.g. `site/<siteId>`, `blog/<blogId>`, `kb-public/<spaceId>`."""
        if not _SCOPE_PATTERN.fullmatch(scope):
            raise BlobValidationError(f'Invalid public scope {scope!r}')
        if not _SHA256_PATTERN.fullmatch(sha256):
            raise BlobValidationError('Public keys are named by the lower-case hex SHA-256 of the content')
        if not _EXT_PATTERN.fullmatch(ext):
            raise BlobValidationError(f'Invalid extension {ext!r}')
        return f'{tenant_id}/{scope}/{sha256}.{ext}'

    def url(self, key: str) -> str:
        return f'{self.base_url}/{key}'

    @abstractmethod
    async def publish(
        self,
        tenant_id: TenantId,
        scope: str,
        *,
        ext: str,
        content_type: str,
        load: Callable[[], Awaitable[bytes]],
        sha256: str | None = None,
    ) -> PublicObject:
        """Copy content to `{tenantId}/{scope}/{sha256}.{ext}` with immutable cache headers.

        With a known `sha256` an existing object is not re-read (`load` is not called); otherwise `load` provides the
        bytes and the hash is computed.
        """

    @abstractmethod
    async def delete_scope(self, tenant_id: TenantId, scope: str) -> int:
        """Delete every object below `{tenantId}/{scope}/` (unpublish); returns the number deleted."""

    @abstractmethod
    async def delete_tenant(self, tenant_id: TenantId) -> int:
        """Offboarding: delete every public object of the tenant."""


@dataclass
class StorageSettings:
    """Private storage tiering (spec §9)."""

    STORAGE_PRIVATE_MODE: str = field(default_factory=lambda: os.getenv('STORAGE_PRIVATE_MODE') or 'pooled')
    STORAGE_PRIVATE_BUCKET: str = field(default_factory=lambda: os.getenv('STORAGE_PRIVATE_BUCKET') or 'taas-private')

    def __post_init__(self) -> None:
        mode = self.STORAGE_PRIVATE_MODE.strip().lower()
        if mode not in ('pooled', 'dedicated'):
            raise BlobValidationError(f'Invalid STORAGE_PRIVATE_MODE {self.STORAGE_PRIVATE_MODE!r}: pooled | dedicated')
        self.STORAGE_PRIVATE_MODE = mode

    @property
    def mode(self) -> StorageMode:
        return 'dedicated' if self.STORAGE_PRIVATE_MODE == 'dedicated' else 'pooled'


@dataclass
class CdnSettings:
    """Public bucket + CDN (spec §9). Credentials default to the `AWS_*` ones of the private storage."""

    CDN_SERVICE_PROVIDER: str = field(default_factory=lambda: (os.getenv('CDN_SERVICE_PROVIDER') or '').strip().lower())
    CDN_BUCKET_NAME: str = field(default_factory=lambda: (os.getenv('CDN_BUCKET_NAME') or '').strip())
    CDN_BUCKET_SERVICE_URL: str = field(default_factory=lambda: (os.getenv('CDN_BUCKET_SERVICE_URL') or '').strip())
    CDN_SERVICE_URL: str = field(default_factory=lambda: (os.getenv('CDN_SERVICE_URL') or '').strip())
    CDN_BUCKET_PUBLIC_URL: str = field(default_factory=lambda: (os.getenv('CDN_BUCKET_PUBLIC_URL') or '').strip())
    CDN_ACCESS_KEY_ID: str = field(default_factory=lambda: (os.getenv('CDN_ACCESS_KEY_ID') or '').strip())
    CDN_SECRET_ACCESS_KEY: str = field(default_factory=lambda: (os.getenv('CDN_SECRET_ACCESS_KEY') or '').strip())

    @property
    def enabled(self) -> bool:
        return bool(self.CDN_SERVICE_PROVIDER and self.CDN_BUCKET_NAME and self.CDN_BUCKET_PUBLIC_URL)

    @property
    def endpoint_url(self) -> str:
        """S3 endpoint of the public bucket: `CDN_BUCKET_SERVICE_URL`, else `CDN_SERVICE_URL`, else `AWS_ENDPOINT_URL`."""
        return self.CDN_BUCKET_SERVICE_URL or self.CDN_SERVICE_URL or (os.getenv('AWS_ENDPOINT_URL') or '').strip()

    @property
    def public_url(self) -> str:
        return self.CDN_BUCKET_PUBLIC_URL.rstrip('/')


@lru_cache(maxsize=1)
def get_storage_settings() -> StorageSettings:
    return StorageSettings()


@lru_cache(maxsize=1)
def get_cdn_settings() -> CdnSettings:
    return CdnSettings()
