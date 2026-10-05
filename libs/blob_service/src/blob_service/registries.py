"""`TenantBucketRegistryT` implementations: SQL (`taas_tenants`) and in-memory (tests)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from foundation.blob import (
    BlobConflictError,
    BlobTenantNotFoundError,
    TenantBucketRecord,
    TenantBucketRegistryT,
    TenantId,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


def parse_tenant_uuid(tenant_id: TenantId) -> UUID | None:
    """`taas_tenants.id` as a UUID; `None` when malformed (such a tenant cannot exist)."""
    if isinstance(tenant_id, UUID):
        return tenant_id
    try:
        return UUID(str(tenant_id))
    except ValueError:
        return None


def _stored_bucket(tenant_id: TenantId, has_bucket: bool, bucket: Any) -> str | None:
    """`sys_settings.bucket`: absent → `None`; present but not a non-empty string → `BlobConflictError`."""
    if not has_bucket:
        return None
    if not isinstance(bucket, str) or not bucket:
        raise BlobConflictError(
            f'Tenant {tenant_id}: sys_settings.bucket is not a non-empty string'
        )
    return bucket


@dataclass(slots=True)
class _MemoryTenant:
    tenant_code: str
    bucket: str | None = None


class MemoryTenantBucketRegistry(TenantBucketRegistryT):
    """In-memory registry: `add_tenant(tenant_id, tenant_code)` then use it like the SQL one."""

    def __init__(self, tenants: dict[str, str] | None = None) -> None:
        """`tenants`: `{tenant_id: tenant_code}`."""
        self._tenants: dict[str, _MemoryTenant] = {}
        for tenant_id, tenant_code in (tenants or {}).items():
            self.add_tenant(tenant_id, tenant_code)

    def add_tenant(
        self, tenant_id: TenantId, tenant_code: str, bucket: str | None = None
    ) -> None:
        self._tenants[str(tenant_id)] = _MemoryTenant(
            tenant_code=tenant_code, bucket=bucket
        )

    def remove_tenant(self, tenant_id: TenantId) -> None:
        self._tenants.pop(str(tenant_id), None)

    async def get(self, tenant_id: TenantId) -> TenantBucketRecord | None:
        tenant = self._tenants.get(str(tenant_id))
        if tenant is None:
            return None
        return TenantBucketRecord(tenant_code=tenant.tenant_code, bucket=tenant.bucket)

    async def set_if_absent(self, tenant_id: TenantId, bucket: str) -> str:
        tenant = self._tenants.get(str(tenant_id))
        if tenant is None:
            raise BlobTenantNotFoundError(f'Tenant not found: {tenant_id}')
        if tenant.bucket is None:
            tenant.bucket = bucket
        return tenant.bucket


_SELECT_SQL: Final = text(
    "SELECT tenant_code, sys_settings ? 'bucket' AS has_bucket, sys_settings -> 'bucket' AS bucket "
    'FROM taas_tenants WHERE id = :tenant_id'
)
_SET_IF_ABSENT_SQL: Final = text(
    'UPDATE taas_tenants '
    "SET sys_settings = sys_settings || jsonb_build_object('bucket', CAST(:bucket AS text)) "
    "WHERE id = :tenant_id AND NOT (sys_settings ? 'bucket')"
)


class SqlTenantBucketRegistry(TenantBucketRegistryT):
    """Reads `taas_tenants.tenant_code` / `sys_settings.bucket`; stores the bucket only if still absent.

    A malformed (non-UUID) tenant id is an unknown tenant; a non-string `sys_settings.bucket` → `BlobConflictError`.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def get(self, tenant_id: TenantId) -> TenantBucketRecord | None:
        tenant_uuid = parse_tenant_uuid(tenant_id)
        if tenant_uuid is None:
            return None
        async with self._engine.connect() as conn:
            row = (await conn.execute(_SELECT_SQL, {'tenant_id': tenant_uuid})).first()
        if row is None:
            return None
        return TenantBucketRecord(
            tenant_code=str(row.tenant_code),
            bucket=_stored_bucket(tenant_id, bool(row.has_bucket), row.bucket),
        )

    async def set_if_absent(self, tenant_id: TenantId, bucket: str) -> str:
        tenant_uuid = parse_tenant_uuid(tenant_id)
        if tenant_uuid is None:
            raise BlobTenantNotFoundError(f'Tenant not found: {tenant_id}')
        async with self._engine.begin() as conn:
            await conn.execute(
                _SET_IF_ABSENT_SQL, {'tenant_id': tenant_uuid, 'bucket': bucket}
            )
        record = await self.get(tenant_uuid)
        if record is None:
            raise BlobTenantNotFoundError(f'Tenant not found: {tenant_id}')
        if record.bucket is None:  # unreachable: the guarded UPDATE stored one
            raise BlobConflictError(
                f'Tenant {tenant_id}: sys_settings.bucket was not stored'
            )
        return record.bucket
