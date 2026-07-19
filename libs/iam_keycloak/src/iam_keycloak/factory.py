"""The factory to create related Keycloak IAM service"""
from db.common import IRepositoryFactory
from foundation.state import get_service
from foundation.state.service_registry import register_service
from foundation.utils.singleton import singleton
from iam.auth.types import IamDirectoryServiceT
from iam.types import IIamServiceFactory

from .adapter.keycloak_starlette_middleware import KeycloakOpenIDAuthBackend
from .db.kc_db_factory import KCDBFactory
from .services.kc_iam_service import KeycloakIamService


@singleton
class KeycloakIamServiceFactory(IIamServiceFactory):
    """
    Factory to create Keycloak IAM service and related components.
    """

    _instance: 'KeycloakIamServiceFactory | None' = None

    def __init__(self):
        super().__init__()
        self._register_services()


    def _register_services(self):
        register_service(IamDirectoryServiceT, KeycloakIamService(self))
        return self

    def get_directory_service(self) -> IamDirectoryServiceT:
        return get_service(IamDirectoryServiceT)

    def get_authentication_backend(self):
        return KeycloakOpenIDAuthBackend()

    def get_repository_factory(self) -> IRepositoryFactory:
        """Create and return an IRepositoryFactory instance."""
        return KCDBFactory()
