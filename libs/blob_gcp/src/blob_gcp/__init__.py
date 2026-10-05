"""Google Cloud Storage adapter implementing `foundation.blob.BlobAdapterT`."""

from .gcp_adapter import DELETE_BATCH_SIZE, GcpBlobAdapter, GcpBlobSettings

__all__ = ['DELETE_BATCH_SIZE', 'GcpBlobAdapter', 'GcpBlobSettings']
