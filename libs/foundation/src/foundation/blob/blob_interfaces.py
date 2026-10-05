"""Blob storage interfaces (contract §4). Implementations live in `blob_s3`, `blob_gcp`, `blob_azure`, `blob_service`."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from .blob_types import (
    BlobBody,
    BlobInfo,
    BlobListOptions,
    BlobObject,
    BlobPage,
    BlobPresignOptions,
    BlobProvider,
    BlobPutOptions,
    TenantBucketRecord,
)

type TenantId = UUID | str
"""`taas_tenants.id` (UUID, or its string form)."""


class BlobAdapterT(ABC):
    """One provider, explicit bucket. Missing objects are `None` on `get` / `head`, never an exception."""

    @property
    @abstractmethod
    def provider(self) -> BlobProvider: ...

    @abstractmethod
    async def ensure_bucket(self, bucket: str) -> None:
        """Idempotent create (already owned → no error); private, no public access."""

    @abstractmethod
    async def bucket_exists(self, bucket: str) -> bool: ...

    @abstractmethod
    async def delete_bucket(self, bucket: str) -> None:
        """Delete an empty bucket; missing → no error; not empty → `BlobConflictError`."""

    @abstractmethod
    async def put(
        self,
        bucket: str,
        key: str,
        body: BlobBody,
        options: BlobPutOptions | None = None,
    ) -> BlobInfo:
        """Store (overwrite) an object; returns the stored `BlobInfo`."""

    @abstractmethod
    async def get(self, bucket: str, key: str) -> BlobObject | None: ...

    @abstractmethod
    async def head(self, bucket: str, key: str) -> BlobInfo | None: ...

    @abstractmethod
    async def exists(self, bucket: str, key: str) -> bool: ...

    @abstractmethod
    async def delete(self, bucket: str, key: str) -> None:
        """Idempotent (missing key → no error)."""

    @abstractmethod
    async def delete_many(self, bucket: str, keys: Sequence[str]) -> None:
        """Idempotent; batches of 1000 where the provider has a batch API."""

    @abstractmethod
    async def list(
        self, bucket: str, options: BlobListOptions | None = None
    ) -> BlobPage:
        """One page of objects (recursive, no delimiter), in key order."""

    @abstractmethod
    async def copy(self, bucket: str, source_key: str, target_key: str) -> None:
        """Server-side copy inside the bucket (content type + metadata kept); missing source → `BlobNotFoundError`."""

    @abstractmethod
    async def presign(
        self, bucket: str, key: str, options: BlobPresignOptions | None = None
    ) -> str:
        """URL usable without credentials (S3: SigV4, GCS: V4 signed URL, Azure: SAS)."""

    async def aclose(self) -> None:  # noqa: B027 - optional hook
        """Release SDK clients (no-op by default)."""


class TenantBlobStoreT(ABC):
    """The object methods of `BlobAdapterT` bound to one tenant's bucket."""

    @property
    @abstractmethod
    def tenant_id(self) -> TenantId: ...

    @property
    @abstractmethod
    def bucket(self) -> str: ...

    @abstractmethod
    async def put(
        self, key: str, body: BlobBody, options: BlobPutOptions | None = None
    ) -> BlobInfo: ...

    @abstractmethod
    async def get(self, key: str) -> BlobObject | None: ...

    @abstractmethod
    async def head(self, key: str) -> BlobInfo | None: ...

    @abstractmethod
    async def exists(self, key: str) -> bool: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    async def delete_many(self, keys: Sequence[str]) -> None: ...

    @abstractmethod
    async def list(self, options: BlobListOptions | None = None) -> BlobPage: ...

    @abstractmethod
    async def copy(self, source_key: str, target_key: str) -> None: ...

    @abstractmethod
    async def presign(
        self, key: str, options: BlobPresignOptions | None = None
    ) -> str: ...


class TenantBucketRegistryT(ABC):
    """Port of the tenant lookup (`taas_tenants.tenant_code` + `sys_settings.bucket`)."""

    @abstractmethod
    async def get(self, tenant_id: TenantId) -> TenantBucketRecord | None:
        """The tenant code and stored bucket, or `None` for an unknown tenant."""

    @abstractmethod
    async def set_if_absent(self, tenant_id: TenantId, bucket: str) -> str:
        """Store `bucket` only if none is stored; returns the stored name (given or set concurrently)."""


class BlobServiceT(ABC):
    """Entry point for consumers: tenant buckets on top of one adapter."""

    @property
    @abstractmethod
    def adapter(self) -> BlobAdapterT: ...

    @abstractmethod
    async def for_tenant(self, tenant_id: TenantId) -> TenantBlobStoreT:
        """The tenant's store; provisions the bucket on first use. Unknown tenant → `BlobTenantNotFoundError`."""

    @abstractmethod
    async def bucket_for(self, tenant_id: TenantId) -> str:
        """The tenant's bucket name (provisions like `for_tenant`)."""

    async def aclose(self) -> None:  # noqa: B027 - optional hook
        """Release the adapter (no-op by default)."""
