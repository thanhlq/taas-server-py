# Blob storage (tenant buckets)

Contract: `taas-specs/blob-storage-service/blob-service-spec.md` — same names, behaviour and settings as the
taas-server-js twin (`@taas/blob-*`).

## Libs

| Lib | Role |
| --- | --- |
| `foundation.blob` | ABCs (`BlobAdapterT`, `TenantBlobStoreT`, `BlobServiceT`, `TenantBucketRegistryT`), types, errors, validation, `BlobSettings`, behaviour suite (`conformance.py`) — no SDK |
| `libs/blob_service` | `create_blob_service()`, `DefaultBlobService`, SQL / memory tenant registries, `MemoryBlobAdapter` |
| `libs/blob_s3` | AWS S3, Cloudflare R2, RustFS (`aiobotocore`) |
| `libs/blob_gcp` | Google Cloud Storage (`google-cloud-storage` in a thread) — extra `blob-service[gcp]` |
| `libs/blob_azure` | Azure Blob Storage (aio, SAS) — extra `blob-service[azure]` |

Consumers depend on `foundation.blob` only and never import an adapter.

## Settings (`.env`, section 8)

| Key | Default | Notes |
| --- | --- | --- |
| `BLOB_STORAGE_PROVIDER` | `s3` | `s3` \| `gcp` (alias `gcs`) \| `azure` \| `memory` |
| `BLOB_BUCKET_PREFIX` | `taas-` | bucket = prefix + `tenant_code`; GCS names are global → deployment prefix |
| `BLOB_PRESIGN_EXPIRES` | `900` | tenant stores' default URL lifetime (an adapter called directly uses 900) |
| `AWS_ENDPOINT_URL`, `AWS_REGION` (→ `AWS_DEFAULT_REGION`), `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_S3_FORCE_PATH_STYLE` | — / `us-east-1` / — / — / `true` with an endpoint | S3 / R2 / RustFS |
| `BLOB_GCP_PROJECT_ID`, `BLOB_GCP_LOCATION` | — / `EU` | ADC / `GOOGLE_APPLICATION_CREDENTIALS` |
| `BLOB_AZURE_CONNECTION_STRING` or `BLOB_AZURE_ACCOUNT_NAME` + `BLOB_AZURE_ACCOUNT_KEY` | — | SAS needs the key |

`foundation.storage.StorageSettings.BLOB_STORAGE_PROVIDER` / `BLOB_STORAGE_BUCKET` are deprecated (kept for
`StorageConfig`); the blob service reads `foundation.blob.BlobSettings`.

## Local run (RustFS)

```bash
# from taas-all
docker compose -f docker-compose.infra.yml up -d storage     # S3 API localhost:19000, console :19001, app / app
```

```dotenv
BLOB_STORAGE_PROVIDER=s3
AWS_ENDPOINT_URL=http://localhost:19000
AWS_ACCESS_KEY_ID=app
AWS_SECRET_ACCESS_KEY=app
AWS_REGION=us-east-1
```

## Getting a tenant store (consumer side)

```python
from blob_service import create_blob_service          # composition root only (app startup)
from foundation.blob import BlobPresignOptions, BlobPutOptions, BlobServiceT
from foundation.state import get_service

create_blob_service(engine=db_engine)                  # registers BlobServiceT

# anywhere (domain code depends on foundation only)
blob = get_service(BlobServiceT)
store = await blob.for_tenant(tenant_id)               # bucket from sys_settings.bucket, provisioned on first use
await store.put(f'tasks/{task_id}/attachments/{name}', data, BlobPutOptions(content_type=mime))
url = await store.presign(f'tasks/{task_id}/attachments/{name}', BlobPresignOptions(download_name=name))
```

- **Apps use the storage resolver, not raw tenant buckets** (next section); `for_tenant` is the low-level contract.
- Keys: 1..1024 UTF-8 bytes, relative, no `.` / `..` / empty segment, no control characters. Metadata keys
  `^[a-z][a-z0-9_]{0,62}$` after lower-casing. Errors: `BlobValidationError`, `BlobNotFoundError`,
  `BlobConflictError`, `BlobTenantNotFoundError`, `BlobProviderError` (stable `code`).
- Missing objects: `get` / `head` → `None`. Missing bucket: `put` / `get` / `list` / `copy` → `BlobNotFoundError`,
  `head` / `exists` → `None` / `False`, `delete` / `delete_many` → no-op.
- Browser uploads: presign a PUT with `content_type`; the client must send exactly that `Content-Type`
  (Azure also `x-ms-blob-type: BlockBlob`).

## Storage resolver and public CDN (taas-specs/storage)

```python
from blob_service import create_blob_service, create_public_store, create_storage_resolver   # app startup
from foundation.blob import PublicStoreT, StorageResolverT, kind_key

blob = create_blob_service(engine=db_engine)
create_storage_resolver(blob, blob.registry)   # STORAGE_PRIVATE_MODE (pooled | dedicated), STORAGE_PRIVATE_BUCKET
create_public_store()                           # CDN_* — DisabledPublicStore when not configured

storage = get_service(StorageResolverT)
docs = await storage.store(tenant_id, 'document')        # keys relative to {tenantId}/documents/ (pooled) or documents/
await docs.put(f'drives/{drive_id}/{file_id}/1', data)
root = await storage.root(tenant_id)                     # keys like kind_key('upload', 'media/…') = 'uploads/media/…'

cdn = get_service(PublicStoreT)
obj = await cdn.publish(tenant_id, f'site/{site_id}', ext='webp', content_type='image/webp', load=read_bytes, sha256=digest)
obj.url    # CDN_BUCKET_PUBLIC_URL/{tenantId}/site/{siteId}/{sha256}.webp — immutable
await cdn.delete_scope(tenant_id, f'site/{site_id}')
```

- Pooled tenants share `STORAGE_PRIVATE_BUCKET` under `{tenantId}/`; dedicated tenants (`sys_settings.storage.mode`,
  or a stored `sys_settings.bucket`) keep `<BLOB_BUCKET_PREFIX><tenant_code>`.
- Kinds: `upload` → `uploads/`, `derived` → `derived/`, `knowledge` → `knowledge/`, `document` → `documents/`.
- Cloudflare R2: private storage on `AWS_ENDPOINT_URL` (`https://<account>.r2.cloudflarestorage.com`, region `auto`);
  the public bucket may live in another jurisdiction (`CDN_BUCKET_SERVICE_URL=https://<account>.eu.r2.cloudflarestorage.com`).
  Public URL: a custom media domain in production (`r2.dev` is rate-limited, development only).

## Tests

```bash
uv run --package foundation pytest libs/foundation/tests/unit          # validation, settings
uv run --package blob-service pytest libs/blob_service/tests/unit      # memory suite, provisioning, factory
uv run --package blob-s3 pytest libs/blob_s3/tests/unit                # + blob_gcp / blob_azure (faked SDKs)
uv run --package blob-s3 pytest libs/blob_s3/tests/unit_dev            # RustFS (skips when down)
uv run --package blob-service pytest libs/blob_service/tests/unit_dev  # RustFS + local Postgres tenants
```

Live tests use bucket prefix `e2e-py-` and delete every bucket and tenant row they create.
