# .venv/lib/python3.13/site-packages/litestar_email/message.py

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from foundation.storage.storage_config import StorageConfig
from foundation.storage.types import StorageBucket
from foundation.utils.cache import lru_cache_ignore_1st_arg
from foundation.utils.env_utils import get_env


@dataclass
class StorageSettings:
    """
    Storage configuration.
    """

    TEMPLATE_STORAGE_PROVIDER: str = field(
        default_factory=get_env('TEMPLATE_STORAGE_PROVIDER', 'fs')
    )

    BLOB_STORAGE_PROVIDER: str = field(
        default_factory=get_env('BLOB_STORAGE_PROVIDER', 's3')
    )
    """
    Values:
        - 'fs' (default) - file system, 's3' - Amazon S3, 'gcs' - Google Cloud Storage, 'azure' - Azure Blob Storage.
        - s3: can be Cloudflare R2, MinIO, etc. as long as it supports S3 API.
    """

    TEMPLATE_STORAGE_BUCKET: str = 'eworksuite-templates'
    """📦 GCS bucket for template storage"""

    BLOB_STORAGE_BUCKET: str = 'eworksuite-blob'
    """📦 GCS bucket for blob storage"""

    @lru_cache_ignore_1st_arg
    def get_config(self) -> StorageConfig:
        return StorageConfig(
            template_storage_provider=self.TEMPLATE_STORAGE_PROVIDER,
            blob_storage_provider=self.BLOB_STORAGE_PROVIDER,
            template_bucket=StorageBucket(
                name=self.TEMPLATE_STORAGE_BUCKET,
                provider=self.TEMPLATE_STORAGE_PROVIDER,
            ),
            blob_bucket=StorageBucket(
                name=self.BLOB_STORAGE_BUCKET,
                provider=self.BLOB_STORAGE_PROVIDER,
            ),
        )


@lru_cache(maxsize=1)
def get_storage_settings() -> StorageSettings:
    """Return the storage settings."""
    return StorageSettings()


@lru_cache(maxsize=1)
def get_storage_config() -> StorageConfig:
    """Return the storage config."""
    return get_storage_settings().get_config()
