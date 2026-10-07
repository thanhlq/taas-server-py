"""Storage resolver (pooled / dedicated private storage) and the public CDN store (taas-specs/platform/storage).

`create_storage_resolver(blob_service, registry)` → `StorageResolverT`; `create_public_store()` → `PublicStoreT`
(S3 compatible: Cloudflare R2, AWS S3 + CloudFront) or a disabled store when no CDN is configured.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace

from foundation.blob import (
    DEFAULT_PRESIGN_EXPIRES,
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
    BlobValidationError,
    TenantBlobStoreT,
    TenantBucketRegistryT,
    TenantId,
)
from foundation.blob.storage import (
    IMMUTABLE_CACHE,
    STORAGE_KIND_PREFIXES,
    CdnSettings,
    PublicObject,
    PublicStoreT,
    StorageKind,
    StorageLocation,
    StorageMode,
    StorageResolverT,
    StorageSettings,
    get_cdn_settings,
    get_storage_settings,
)
from foundation.observability.log_factory import LogFactory
from foundation.state import register_service


class PrefixedTenantBlobStore(TenantBlobStoreT):
    """A tenant store whose keys are relative to `prefix` in `bucket` (pooled tenant roots, storage kinds)."""

    __slots__ = ('_adapter', '_bucket', '_prefix', '_presign_expires', '_tenant_id')

    def __init__(
        self,
        adapter: BlobAdapterT,
        tenant_id: TenantId,
        bucket: str,
        prefix: str,
        presign_expires: int = DEFAULT_PRESIGN_EXPIRES,
    ) -> None:
        if prefix and not prefix.endswith('/'):
            raise BlobValidationError(f'Store prefix must end with "/": {prefix!r}')
        self._adapter = adapter
        self._tenant_id = tenant_id
        self._bucket = bucket
        self._prefix = prefix
        self._presign_expires = presign_expires

    @property
    def tenant_id(self) -> TenantId:
        return self._tenant_id

    @property
    def bucket(self) -> str:
        return self._bucket

    @property
    def prefix(self) -> str:
        return self._prefix

    def _key(self, key: str) -> str:
        if not key or key.startswith('/'):
            raise BlobValidationError(f'Invalid relative key {key!r}')
        return f'{self._prefix}{key}'

    def _relative(self, info: BlobInfo) -> BlobInfo:
        return replace(info, key=info.key[len(self._prefix) :])

    async def put(self, key: str, body: BlobBody, options: BlobPutOptions | None = None) -> BlobInfo:
        return self._relative(await self._adapter.put(self._bucket, self._key(key), body, options))

    async def get(self, key: str) -> BlobObject | None:
        found = await self._adapter.get(self._bucket, self._key(key))
        return None if found is None else replace(found, info=self._relative(found.info))

    async def head(self, key: str) -> BlobInfo | None:
        found = await self._adapter.head(self._bucket, self._key(key))
        return None if found is None else self._relative(found)

    async def exists(self, key: str) -> bool:
        return await self._adapter.exists(self._bucket, self._key(key))

    async def delete(self, key: str) -> None:
        await self._adapter.delete(self._bucket, self._key(key))

    async def delete_many(self, keys: Sequence[str]) -> None:
        await self._adapter.delete_many(self._bucket, [self._key(k) for k in keys])

    async def copy(self, source_key: str, target_key: str) -> None:
        await self._adapter.copy(self._bucket, self._key(source_key), self._key(target_key))

    async def presign(self, key: str, options: BlobPresignOptions | None = None) -> str:
        options = options or BlobPresignOptions()
        if options.expires_in is None:
            options = replace(options, expires_in=self._presign_expires)
        return await self._adapter.presign(self._bucket, self._key(key), options)

    async def list(self, options: BlobListOptions | None = None) -> BlobPage:
        options = options or BlobListOptions()
        cursor = f'{self._prefix}{options.cursor}' if options.cursor else None
        page = await self._adapter.list(
            self._bucket,
            replace(options, prefix=f'{self._prefix}{options.prefix or ""}', cursor=cursor),
        )
        next_cursor = page.next_cursor
        if next_cursor and next_cursor.startswith(self._prefix):
            next_cursor = next_cursor[len(self._prefix) :]
        return BlobPage(items=[self._relative(i) for i in page.items], next_cursor=next_cursor)


class DefaultStorageResolver(StorageResolverT):
    """Pooled tenants: `STORAGE_PRIVATE_BUCKET` + `{tenantId}/`; dedicated: the tenant bucket of `BlobServiceT`.

    A tenant is dedicated when its `sys_settings.storage.mode` says so or when a bucket is already stored for it
    (blob contract §2); otherwise the platform default mode applies.
    """

    def __init__(
        self,
        blob: BlobServiceT,
        registry: TenantBucketRegistryT,
        *,
        default_mode: StorageMode = 'pooled',
        pooled_bucket: str = 'taas-private',
        region: str = 'auto',
        presign_expires: int = DEFAULT_PRESIGN_EXPIRES,
    ) -> None:
        self._blob = blob
        self._registry = registry
        self._default_mode: StorageMode = default_mode
        self._pooled_bucket = pooled_bucket
        self._region = region
        self._presign_expires = presign_expires
        self._modes: dict[str, StorageMode] = {}
        self._dedicated_ready: set[str] = set()
        self._pooled_ready = False
        self._lock = asyncio.Lock()

    @property
    def default_mode(self) -> StorageMode:
        return self._default_mode

    @property
    def pooled_bucket(self) -> str:
        return self._pooled_bucket

    async def mode_of(self, tenant_id: TenantId) -> StorageMode:
        cached = self._modes.get(str(tenant_id))
        if cached is not None:
            return cached
        record = await self._registry.get(tenant_id)
        if record is None:
            raise BlobTenantNotFoundError(f'Tenant not found: {tenant_id}')
        mode: StorageMode
        if record.storage_mode in ('pooled', 'dedicated'):
            mode = 'dedicated' if record.storage_mode == 'dedicated' else 'pooled'
        elif record.bucket:
            mode = 'dedicated'
        else:
            mode = self._default_mode
        self._modes[str(tenant_id)] = mode
        return mode

    async def _root(self, tenant_id: TenantId) -> tuple[str, str, StorageMode]:
        mode = await self.mode_of(tenant_id)
        if mode == 'dedicated':
            bucket = await self._blob.bucket_for(tenant_id)
            if bucket not in self._dedicated_ready:
                # idempotent: a stored bucket survives a provider switch (e.g. RustFS → R2) by being created again
                await self._blob.adapter.ensure_bucket(bucket)
                self._dedicated_ready.add(bucket)
            return bucket, '', mode
        if not self._pooled_ready:
            async with self._lock:
                if not self._pooled_ready:
                    await self._blob.adapter.ensure_bucket(self._pooled_bucket)
                    self._pooled_ready = True
        return self._pooled_bucket, f'{tenant_id}/', mode

    async def resolve(self, tenant_id: TenantId, kind: StorageKind) -> StorageLocation:
        bucket, root, mode = await self._root(tenant_id)
        return StorageLocation(bucket=bucket, prefix=f'{root}{STORAGE_KIND_PREFIXES[kind]}', region=self._region, mode=mode)

    async def store(self, tenant_id: TenantId, kind: StorageKind) -> TenantBlobStoreT:
        location = await self.resolve(tenant_id, kind)
        return PrefixedTenantBlobStore(
            self._blob.adapter, tenant_id, location.bucket, location.prefix, self._presign_expires
        )

    async def root(self, tenant_id: TenantId) -> TenantBlobStoreT:
        bucket, root, _ = await self._root(tenant_id)
        return PrefixedTenantBlobStore(self._blob.adapter, tenant_id, bucket, root, self._presign_expires)

    def clear_cache(self) -> None:
        self._modes.clear()
        self._dedicated_ready.clear()


class AdapterPublicStore(PublicStoreT):
    """Public bucket on any adapter (S3 / R2 in production, memory in tests)."""

    def __init__(self, adapter: BlobAdapterT, bucket: str, base_url: str) -> None:
        self._adapter = adapter
        self._bucket = bucket
        self._base_url = base_url.rstrip('/')

    @property
    def enabled(self) -> bool:
        return True

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def bucket(self) -> str:
        return self._bucket

    @property
    def adapter(self) -> BlobAdapterT:
        return self._adapter

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
        data: bytes | None = None
        if sha256 is None:
            data = await load()
            sha256 = hashlib.sha256(data).hexdigest()
        key = self.key(tenant_id, scope, sha256, ext)
        if await self._adapter.exists(self._bucket, key):
            return PublicObject(key=key, url=self.url(key), created=False)
        if data is None:
            data = await load()
            if hashlib.sha256(data).hexdigest() != sha256:
                raise BlobValidationError(f'Content does not match its SHA-256 ({key})')
        await self._adapter.put(
            self._bucket, key, data, BlobPutOptions(content_type=content_type, cache_control=IMMUTABLE_CACHE)
        )
        return PublicObject(key=key, url=self.url(key), created=True)

    async def _delete_prefix(self, prefix: str) -> int:
        deleted = 0
        cursor: str | None = None
        while True:
            page = await self._adapter.list(self._bucket, BlobListOptions(prefix=prefix, cursor=cursor, limit=1000))
            keys = [i.key for i in page.items]
            if keys:
                await self._adapter.delete_many(self._bucket, keys)
                deleted += len(keys)
            if not page.next_cursor:
                return deleted
            cursor = page.next_cursor

    async def delete_scope(self, tenant_id: TenantId, scope: str) -> int:
        self.key(tenant_id, scope, '0' * 64, 'x')  # validates the scope
        return await self._delete_prefix(f'{tenant_id}/{scope}/')

    async def delete_tenant(self, tenant_id: TenantId) -> int:
        if not str(tenant_id).strip():
            raise BlobValidationError('Tenant id must not be empty')
        return await self._delete_prefix(f'{tenant_id}/')


class DisabledPublicStore(PublicStoreT):
    """No CDN configured: nothing is published (sites fall back to renderer-served files)."""

    @property
    def enabled(self) -> bool:
        return False

    @property
    def base_url(self) -> str:
        return ''

    async def publish(self, tenant_id: TenantId, scope: str, **_: object) -> PublicObject:  # type: ignore[override]
        raise BlobValidationError('No CDN is configured (CDN_SERVICE_PROVIDER / CDN_BUCKET_NAME / CDN_BUCKET_PUBLIC_URL)')

    async def delete_scope(self, tenant_id: TenantId, scope: str) -> int:
        return 0

    async def delete_tenant(self, tenant_id: TenantId) -> int:
        return 0


def create_storage_resolver(
    blob: BlobServiceT,
    registry: TenantBucketRegistryT,
    settings: StorageSettings | None = None,
    *,
    region: str | None = None,
    register: bool = True,
) -> DefaultStorageResolver:
    """Build the resolver on the blob service (same adapter) and register it as `StorageResolverT`."""
    settings = settings or get_storage_settings()
    presign = getattr(blob, 'presign_expires', DEFAULT_PRESIGN_EXPIRES)
    resolver = DefaultStorageResolver(
        blob,
        registry,
        default_mode=settings.mode,
        pooled_bucket=settings.STORAGE_PRIVATE_BUCKET,
        region=region or os.getenv('AWS_REGION') or 'auto',
        presign_expires=presign,
    )
    if register:
        register_service(StorageResolverT, resolver)
    LogFactory().get_logger().info(
        f'Storage resolver initialised: default mode={settings.mode}, pooled bucket={settings.STORAGE_PRIVATE_BUCKET!r}'
    )
    return resolver


def create_public_store(
    settings: CdnSettings | None = None,
    adapter: BlobAdapterT | None = None,
    *,
    register: bool = True,
) -> PublicStoreT:
    """`AdapterPublicStore` on an S3 adapter pointed at the public bucket, or `DisabledPublicStore`."""
    settings = settings or get_cdn_settings()
    store: PublicStoreT
    if not settings.enabled:
        store = DisabledPublicStore()
    else:
        if adapter is None:
            if settings.CDN_SERVICE_PROVIDER not in ('cloudflare', 'r2', 'aws', 's3'):
                raise BlobValidationError(
                    f'Unsupported CDN_SERVICE_PROVIDER {settings.CDN_SERVICE_PROVIDER!r}: cloudflare | aws'
                )
            from blob_s3 import S3BlobAdapter, S3BlobSettings

            base = S3BlobSettings()
            adapter = S3BlobAdapter(
                S3BlobSettings(
                    AWS_ENDPOINT_URL=settings.endpoint_url,
                    AWS_REGION=base.AWS_REGION,
                    AWS_ACCESS_KEY_ID=settings.CDN_ACCESS_KEY_ID or base.AWS_ACCESS_KEY_ID,
                    AWS_SECRET_ACCESS_KEY=settings.CDN_SECRET_ACCESS_KEY or base.AWS_SECRET_ACCESS_KEY,
                    AWS_S3_FORCE_PATH_STYLE=base.AWS_S3_FORCE_PATH_STYLE,
                )
            )
        store = AdapterPublicStore(adapter, settings.CDN_BUCKET_NAME, settings.public_url)
    if register:
        register_service(PublicStoreT, store)
    LogFactory().get_logger().info(
        f'Public store initialised: {"bucket " + settings.CDN_BUCKET_NAME + " → " + settings.public_url if store.enabled else "disabled (no CDN)"}'
    )
    return store
