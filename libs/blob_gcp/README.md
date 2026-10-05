# blob-gcp

`GcpBlobAdapter`: `foundation.blob.BlobAdapterT` for Google Cloud Storage (`google-cloud-storage`, sync SDK run in
`asyncio.to_thread`). Used when `BLOB_STORAGE_PROVIDER=gcp` (alias `gcs`); install `blob-service[gcp]`.

- Settings (`GcpBlobSettings`): `BLOB_GCP_PROJECT_ID` (else the credentials' project), `BLOB_GCP_LOCATION`
  (default `EU`). Credentials: `GOOGLE_APPLICATION_CREDENTIALS` / ADC.
- New buckets: uniform bucket-level access, public access prevention enforced. Bucket names are global: use a
  deployment-specific `BLOB_BUCKET_PREFIX` (e.g. `acme-prod-`).
- Presigned URLs are V4 signed URLs: the credentials must be able to sign (service-account key, or IAM signBlob).
  A presigned PUT signs `Content-Type`.
- `delete_many` deletes one object per request (`Bucket.delete_blobs`, missing keys ignored).

```bash
uv run --package blob-gcp pytest libs/blob_gcp/tests/unit   # faked SDK client + offline V4 signing
```

Live tests are not automated yet (opt in with real credentials).
