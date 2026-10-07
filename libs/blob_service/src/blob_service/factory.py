"""Entry point: `create_blob_service()` builds the adapter for `BLOB_STORAGE_PROVIDER` and registers `BlobServiceT`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from foundation.blob import (
    BlobAdapterT,
    BlobServiceT,
    BlobSettings,
    BlobValidationError,
    TenantBucketRegistryT,
    get_blob_settings,
)
from foundation.observability.log_factory import LogFactory
from foundation.state import register_service

from .registries import SqlTenantBucketRegistry
from .service import DefaultBlobService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine


def create_blob_adapter(settings: BlobSettings | None = None) -> BlobAdapterT:
    """The adapter of the configured provider (SDK packages are imported lazily).

    Called directly, an adapter presigns for 900 s by default; tenant stores use `BLOB_PRESIGN_EXPIRES`.
    """
    settings = settings or get_blob_settings()
    match settings.provider:
        case 's3':
            from blob_s3 import S3BlobAdapter

            return S3BlobAdapter()
        case 'gcp':
            try:
                from blob_gcp import GcpBlobAdapter
            except ImportError as e:  # pragma: no cover - depends on the install
                raise ImportError(
                    "BLOB_STORAGE_PROVIDER=gcp needs the 'blob-gcp' package"
                ) from e
            return GcpBlobAdapter()
        case 'azure':
            try:
                from blob_azure import AzureBlobAdapter
            except ImportError as e:  # pragma: no cover - depends on the install
                raise ImportError(
                    "BLOB_STORAGE_PROVIDER=azure needs the 'blob-azure' package"
                ) from e
            return AzureBlobAdapter()
        case 'memory':
            from .memory_adapter import MemoryBlobAdapter

            return MemoryBlobAdapter()


def create_blob_service(
    settings: BlobSettings | None = None,
    adapter: BlobAdapterT | None = None,
    registry: TenantBucketRegistryT | None = None,
    *,
    engine: AsyncEngine | None = None,
    register: bool = True,
) -> DefaultBlobService:
    """Build a `DefaultBlobService` and (by default) register it as `BlobServiceT` in `foundation.state`.

    Args:
        settings: defaults to `get_blob_settings()` (environment).
        adapter: defaults to the adapter of `settings.provider`.
        registry: tenant lookup; defaults to `SqlTenantBucketRegistry(engine)`.
        engine: SQLAlchemy `AsyncEngine` of the platform database (when `registry` is not given).
        register: register the service with `foundation.state.register_service`.
    """
    settings = settings or get_blob_settings()
    if registry is None:
        if engine is None:
            raise BlobValidationError(
                'create_blob_service needs a registry or an AsyncEngine (engine=…)'
            )
        registry = SqlTenantBucketRegistry(engine)
    adapter = adapter or create_blob_adapter(settings)
    service = DefaultBlobService(
        adapter,
        registry,
        bucket_prefix=settings.BLOB_BUCKET_PREFIX,
        presign_expires=settings.BLOB_PRESIGN_EXPIRES,
    )
    if register:
        register_service(BlobServiceT, service)
    LogFactory().get_logger().info(
        f'Blob service initialised: provider={adapter.provider}, bucket prefix={settings.BLOB_BUCKET_PREFIX!r}'
    )
    return service
