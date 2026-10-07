# blob-service

Tenant-based blob storage (contract: `taas-specs/platform/storage/blob-service/blob-service-spec.md`, same names and
behaviour as `@taas/blob-service` in taas-server-js). Consumers depend on `foundation.blob` and get a
`BlobServiceT` from this package; they never import an adapter.

| Module | Content |
| --- | --- |
| `factory.py` | `create_blob_service(settings=None, adapter=None, registry=None, *, engine=None, register=True)` → `DefaultBlobService`, registered as `BlobServiceT` in `foundation.state`; `create_blob_adapter(settings)` picks the adapter by `BLOB_STORAGE_PROVIDER` (lazy imports) |
| `service.py` | `DefaultBlobService` (`for_tenant`, `bucket_for`, per-process cache, concurrent first calls agree), `BoundTenantBlobStore` (presign default `BLOB_PRESIGN_EXPIRES`) |
| `registries.py` | `SqlTenantBucketRegistry(engine: AsyncEngine)` on `taas_tenants` (raw SQL), `MemoryTenantBucketRegistry` |
| `memory_adapter.py` | `MemoryBlobAdapter` (tests / local dev, same validation and semantics) |

Tenant bucket = `BLOB_BUCKET_PREFIX + tenant_code` (e.g. `taas-12345678`), stored in
`taas_tenants.sys_settings.bucket` (source of truth once set) with
`sys_settings || jsonb_build_object('bucket', …)` guarded by `NOT (sys_settings ? 'bucket')`, then re-read.
Non-UUID tenant id → `BlobTenantNotFoundError`; empty id → `BlobValidationError`; non-string stored bucket →
`BlobConflictError`.

```python
from blob_service import create_blob_service

service = create_blob_service(engine=db_engine)          # BLOB_* settings from the environment
store = await service.for_tenant(tenant_id)              # provisions the bucket on first use
await store.put(f'projects/{project_id}/spec.pdf', data, BlobPutOptions(content_type='application/pdf'))
url = await store.presign(f'projects/{project_id}/spec.pdf', BlobPresignOptions(download_name='spec.pdf'))
```

Extras: `blob-service[gcp]`, `blob-service[azure]` (`blob-s3` is always installed: default provider).

## Tests

```bash
uv run --package blob-service pytest libs/blob_service/tests/unit       # memory adapter + service (no infra)
uv run --package blob-service pytest libs/blob_service/tests/unit_dev   # RustFS :19000 + local Postgres (.env.test)
```

`unit_dev` skips when RustFS or the database is unreachable and refuses non-local database hosts; it inserts
throwaway `taas_tenants` rows and `e2e-py-…` buckets and deletes them at teardown. The shared behaviour suite
lives in `foundation.blob.conformance`.
