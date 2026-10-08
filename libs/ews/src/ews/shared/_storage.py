"""The tenant's private storage for the business apps (taas-specs/platform/storage): always through the
registered ``StorageResolverT`` (pooled / dedicated), never a bucket picked in app code.

``use_storage(resolver)`` swaps the resolver (tests); ``tenant_root(tenant)`` = the tenant root store whose keys
start with a kind prefix (``documents/…``, ``knowledge/…`` — build them with ``foundation.blob.kind_key``).
"""

from __future__ import annotations

from uuid import UUID

from foundation.blob import StorageResolverT, TenantBlobStoreT
from foundation.state import get_service

_override: list[StorageResolverT | None] = [None]


def use_storage(resolver: StorageResolverT | None) -> StorageResolverT | None:
    """Replace the registered storage resolver (tests); ``None`` restores ``foundation.state``. Returns the previous
    override so a test can put it back."""
    previous, _override[0] = _override[0], resolver
    return previous


def storage_resolver() -> StorageResolverT:
    return _override[0] or get_service(StorageResolverT)


async def tenant_root(tenant_id: UUID | str) -> TenantBlobStoreT:
    """The tenant root of the private storage (keys start with ``uploads/``, ``derived/``, ``documents/`` …)."""
    return await storage_resolver().root(tenant_id)
