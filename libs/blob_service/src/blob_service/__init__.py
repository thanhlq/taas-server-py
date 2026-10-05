"""Tenant-based blob service: picks the adapter, resolves / provisions tenant buckets, memory adapter."""

from .factory import create_blob_adapter, create_blob_service
from .memory_adapter import MemoryBlobAdapter
from .registries import (
    MemoryTenantBucketRegistry,
    SqlTenantBucketRegistry,
    parse_tenant_uuid,
)
from .service import BoundTenantBlobStore, DefaultBlobService

__all__ = [
    'BoundTenantBlobStore',
    'DefaultBlobService',
    'MemoryBlobAdapter',
    'MemoryTenantBucketRegistry',
    'SqlTenantBucketRegistry',
    'create_blob_adapter',
    'create_blob_service',
    'parse_tenant_uuid',
]
