from dataclasses import dataclass

from foundation.storage.types import StorageBucket


@dataclass(frozen=True, slots=True, kw_only=True)
class StorageConfig:
    """Storage configuration."""

    template_storage_provider: str
    blob_storage_provider: str

    template_bucket: StorageBucket
    blob_bucket: StorageBucket
