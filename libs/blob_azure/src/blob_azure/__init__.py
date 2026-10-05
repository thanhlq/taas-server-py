"""Azure Blob Storage adapter (aio + SAS) implementing `foundation.blob.BlobAdapterT`."""

from .azure_adapter import DELETE_BATCH_SIZE, AzureBlobAdapter, AzureBlobSettings

__all__ = ['DELETE_BATCH_SIZE', 'AzureBlobAdapter', 'AzureBlobSettings']
