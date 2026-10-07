# blob

Tenant-based blob storage definitions only (no cloud SDK): ABCs `BlobAdapterT`, `TenantBlobStoreT`, `BlobServiceT`,
`TenantBucketRegistryT`; frozen value types; errors with stable `code`; key / bucket / metadata validation;
`BlobSettings` (`BLOB_STORAGE_PROVIDER`, `BLOB_BUCKET_PREFIX`, `BLOB_PRESIGN_EXPIRES`); `storage.py` = content storage
contract (`StorageResolverT`, `StorageKind`, `StorageLocation`, `PublicStoreT`, `kind_key`, `StorageSettings`, `CdnSettings`,
spec `taas-specs/platform/storage`); `conformance.py` = the
shared adapter behaviour suite. Contract: `taas-specs/platform/storage/blob-service/blob-service-spec.md` (Node twin:
`@taas/foundation/blob`). Implementations: `libs/blob_s3`, `libs/blob_gcp`, `libs/blob_azure`, `libs/blob_service`.
