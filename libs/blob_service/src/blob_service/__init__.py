"""Tenant-based blob service: picks the adapter, resolves / provisions tenant buckets, memory adapter; storage
resolver (pooled / dedicated private storage) and the public CDN store (taas-specs/platform/storage)."""

from .factory import create_blob_adapter, create_blob_service
from .memory_adapter import MemoryBlobAdapter
from .registries import (
    MemoryTenantBucketRegistry,
    SqlTenantBucketRegistry,
    parse_tenant_uuid,
)
from .service import BoundTenantBlobStore, DefaultBlobService
from .storage import (
    AdapterPublicStore,
    DefaultStorageResolver,
    DisabledPublicStore,
    PrefixedTenantBlobStore,
    create_public_store,
    create_storage_resolver,
)

__all__ = [
    'AdapterPublicStore',
    'DefaultStorageResolver',
    'DisabledPublicStore',
    'PrefixedTenantBlobStore',
    'create_public_store',
    'create_storage_resolver',
    'BoundTenantBlobStore',
    'DefaultBlobService',
    'MemoryBlobAdapter',
    'MemoryTenantBucketRegistry',
    'SqlTenantBucketRegistry',
    'create_blob_adapter',
    'create_blob_service',
    'parse_tenant_uuid',
]
