"""`DefaultBlobService`: tenant bucket resolution / provisioning on top of one adapter (contract §2)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import replace
from uuid import UUID

from foundation.blob import (
    DEFAULT_PRESIGN_EXPIRES,
    BlobValidationError,
    resolve_presign_expires,
    BlobAdapterT,
    BlobBody,
    BlobInfo,
    BlobListOptions,
    BlobObject,
    BlobPage,
    BlobPresignOptions,
    BlobPutOptions,
    BlobServiceT,
    BlobTenantNotFoundError,
    TenantBlobStoreT,
    TenantBucketRegistryT,
    TenantId,
    get_blob_settings,
    validate_bucket_name,
)


class BoundTenantBlobStore(TenantBlobStoreT):
    """`TenantBlobStoreT` delegating to the adapter with the tenant's bucket."""

    __slots__ = ('_adapter', '_bucket', '_presign_expires', '_tenant_id')

    def __init__(
        self,
        adapter: BlobAdapterT,
        tenant_id: TenantId,
        bucket: str,
        presign_expires: int = DEFAULT_PRESIGN_EXPIRES,
    ) -> None:
        self._adapter = adapter
        self._tenant_id = tenant_id
        self._bucket = bucket
        self._presign_expires = presign_expires

    @property
    def tenant_id(self) -> TenantId:
        return self._tenant_id

    @property
    def bucket(self) -> str:
        return self._bucket

    async def put(
        self, key: str, body: BlobBody, options: BlobPutOptions | None = None
    ) -> BlobInfo:
        return await self._adapter.put(self._bucket, key, body, options)

    async def get(self, key: str) -> BlobObject | None:
        return await self._adapter.get(self._bucket, key)

    async def head(self, key: str) -> BlobInfo | None:
        return await self._adapter.head(self._bucket, key)

    async def exists(self, key: str) -> bool:
        return await self._adapter.exists(self._bucket, key)

    async def delete(self, key: str) -> None:
        await self._adapter.delete(self._bucket, key)

    async def delete_many(self, keys: Sequence[str]) -> None:
        await self._adapter.delete_many(self._bucket, keys)

    async def copy(self, source_key: str, target_key: str) -> None:
        await self._adapter.copy(self._bucket, source_key, target_key)

    async def presign(self, key: str, options: BlobPresignOptions | None = None) -> str:
        """`expires_in` defaults to `BLOB_PRESIGN_EXPIRES` (the service setting)."""
        options = options or BlobPresignOptions()
        if options.expires_in is None:
            options = replace(options, expires_in=self._presign_expires)
        return await self._adapter.presign(self._bucket, key, options)

    async def list(self, options: BlobListOptions | None = None) -> BlobPage:
        return await self._adapter.list(self._bucket, options)


class DefaultBlobService(BlobServiceT):
    """Resolves `sys_settings.bucket`, provisions `<prefix><tenant_code>` when absent, caches per process.

    Provisioning: `ensure_bucket(prefix + tenant_code)`, then `registry.set_if_absent` (stores the name only if
    still absent) and use the name it returns, so concurrent first calls — in this process or others — agree.
    """

    def __init__(
        self,
        adapter: BlobAdapterT,
        registry: TenantBucketRegistryT,
        *,
        bucket_prefix: str | None = None,
        presign_expires: int | None = None,
    ) -> None:
        self._adapter = adapter
        self._registry = registry
        self._bucket_prefix = (
            get_blob_settings().BLOB_BUCKET_PREFIX
            if bucket_prefix is None
            else bucket_prefix
        )
        expires = (
            get_blob_settings().BLOB_PRESIGN_EXPIRES
            if presign_expires is None
            else presign_expires
        )
        self._presign_expires = resolve_presign_expires(BlobPresignOptions(), expires)
        self._buckets: dict[str, str] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    @property
    def adapter(self) -> BlobAdapterT:
        return self._adapter

    @property
    def registry(self) -> TenantBucketRegistryT:
        """The tenant lookup (shared with the storage resolver)."""
        return self._registry

    @property
    def bucket_prefix(self) -> str:
        return self._bucket_prefix

    @property
    def presign_expires(self) -> int:
        """Default lifetime of the tenant stores' presigned URLs (`BLOB_PRESIGN_EXPIRES`)."""
        return self._presign_expires

    def clear_cache(self) -> None:
        """Forget resolved buckets (e.g. after a tenant is deleted)."""
        self._buckets.clear()

    async def for_tenant(self, tenant_id: TenantId) -> TenantBlobStoreT:
        bucket = await self.bucket_for(tenant_id)
        return BoundTenantBlobStore(
            self._adapter, tenant_id, bucket, self._presign_expires
        )

    async def bucket_for(self, tenant_id: TenantId) -> str:
        if not isinstance(tenant_id, UUID) and not str(tenant_id or '').strip():
            raise BlobValidationError('Tenant id must be a non-empty string or UUID')
        cache_key = str(tenant_id)
        cached = self._buckets.get(cache_key)
        if cached is not None:
            return cached
        lock = self._locks.setdefault(cache_key, asyncio.Lock())
        try:
            async with lock:
                cached = self._buckets.get(cache_key)
                if cached is None:
                    cached = await self._resolve(tenant_id)
                    self._buckets[cache_key] = cached
                return cached
        finally:
            if not lock.locked():
                self._locks.pop(cache_key, None)

    async def _resolve(self, tenant_id: TenantId) -> str:
        record = await self._registry.get(tenant_id)
        if record is None:
            raise BlobTenantNotFoundError(f'Tenant not found: {tenant_id}')
        if record.bucket:
            return record.bucket
        bucket = validate_bucket_name(f'{self._bucket_prefix}{record.tenant_code}')
        await self._adapter.ensure_bucket(bucket)
        return await self._registry.set_if_absent(tenant_id, bucket)

    async def aclose(self) -> None:
        await self._adapter.aclose()
