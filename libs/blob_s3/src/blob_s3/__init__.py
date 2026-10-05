"""S3 compatible blob adapter (AWS S3, Cloudflare R2, RustFS) implementing `foundation.blob.BlobAdapterT`."""

from .s3_adapter import DELETE_BATCH_SIZE, S3BlobAdapter
from .s3_settings import S3BlobSettings

__all__ = ['DELETE_BATCH_SIZE', 'S3BlobAdapter', 'S3BlobSettings']
