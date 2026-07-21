from foundation.state import register_service
from foundation.storage.providers.fs.fs_template_storage import FSTemplateStorage
from foundation.storage.storage_config import StorageConfig
from foundation.storage.storage_settings import get_storage_config
from foundation.storage.types import TemplateStorageServiceT
from foundation.utils.singleton import singleton


@singleton
class StorageServiceFactory:
    # TODO to move to generic type
    _template_storage_service: FSTemplateStorage | None = None
    _blob_storage_service: str

    def __init__(self):
        """
        Initialize the StorageServiceFactory singleton instance.
        And register the storage service provider based on the configuration.
        """
        storage_config = get_storage_config()

        if storage_config.template_storage_provider == 'fs':
            from .providers.fs import FSTemplateStorage

            StorageServiceFactory._template_storage_service = FSTemplateStorage()

            register_service(
                TemplateStorageServiceT,
                StorageServiceFactory._template_storage_service,
                singleton=True,
            )
        else:
            raise NotImplementedError(
                f"Template storage provider '{storage_config.template_storage_provider}' is not implemented."
            )

    @staticmethod
    def get_storage_config() -> StorageConfig:
        return get_storage_config()

    @staticmethod
    def get_template_storage_service() -> TemplateStorageServiceT:
        return StorageServiceFactory._template_storage_service  # type: ignore
