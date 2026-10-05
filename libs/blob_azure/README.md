# blob-azure

`AzureBlobAdapter`: `foundation.blob.BlobAdapterT` for Azure Blob Storage (`azure-storage-blob` aio). A tenant
bucket is a private *container* of the storage account. Used when `BLOB_STORAGE_PROVIDER=azure`; install
`blob-service[azure]`.

- Settings (`AzureBlobSettings`): `BLOB_AZURE_CONNECTION_STRING`, or `BLOB_AZURE_ACCOUNT_NAME` +
  `BLOB_AZURE_ACCOUNT_KEY`. SAS signing needs the account key (also read from the connection string).
- Presigned URLs are blob SAS (`r` for GET, `cw` for PUT). **A presigned PUT must send the header
  `x-ms-blob-type: BlockBlob`** (Azure requirement) and the `Content-Type` to store (not enforced by the SAS).
- Metadata keys must be C# identifiers: the shared rule `^[a-z][a-z0-9_]{0,62}$` (no `-`) keeps them portable.
- `delete_bucket` refuses a non-empty container (`BlobConflictError`); `delete_many` uses the blob batch API
  (256 per batch); `copy` is a server-side copy, polled until done.

```bash
uv run --package blob-azure pytest libs/blob_azure/tests/unit   # faked SDK client + offline SAS signing
```

Live tests are not automated yet (opt in with a storage account or Azurite).
