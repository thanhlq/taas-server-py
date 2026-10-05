# blob-s3

`S3BlobAdapter`: `foundation.blob.BlobAdapterT` for S3 compatible storage — AWS S3, Cloudflare R2, RustFS (local)
— on `aiobotocore` (async). Built by `blob_service.create_blob_service()` when `BLOB_STORAGE_PROVIDER=s3`.

- Settings (`S3BlobSettings`): `AWS_ENDPOINT_URL` (empty = AWS), `AWS_REGION` → `AWS_DEFAULT_REGION` →
  `us-east-1` (R2: `auto`), `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` (else the SDK default chain),
  `AWS_S3_FORCE_PATH_STYLE` (default: `true` when an endpoint is set).
- SigV4 presigned GET / PUT; a presigned PUT signs `Content-Type`, so the uploader must send exactly that type.
- Checksums only when required (R2 / RustFS compatibility); `delete_many` uses `DeleteObjects` (1000 per request).
- `put` returns `last_modified=None`; `list` items have `content_type=None` and empty `metadata` (S3 API limits).
- Inject a client for tests: `S3BlobAdapter(settings, client=fake)` (an injected client is not closed by `aclose`).

```bash
uv run --package blob-s3 pytest libs/blob_s3/tests/unit       # fake client + offline presigning
uv run --package blob-s3 pytest libs/blob_s3/tests/unit_dev   # behaviour suite on RustFS localhost:19000 (app/app)
```

Local RustFS: `docker compose -f docker-compose.infra.yml up -d storage` (from taas-all). Live tests create and
delete `e2e-py-…` buckets only.
