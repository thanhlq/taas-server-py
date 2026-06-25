"""The factory to create related Keycloak IAM service"""

from core.db.types import IRepositoryFactory
from core.iam.types import IIamService, IIamServiceFactory
from core.services.factory import AbstractServiceFactory

from .adapter.keycloak_starlette_middleware import KeycloakOpenIDAuthBackend
from .db.kc_db_factory import KCDBFactory
from .services.kc_iam_service import KeycloakIamService


class IamKeycloakServiceFactory(IIamServiceFactory, AbstractServiceFactory):
    """
    Factory to create Keycloak IAM service and related components.
    """

    _instance: 'IamKeycloakServiceFactory | None' = None

    # def __new__(cls):
    #     if cls._instance is None:
    #         cls._instance = IamKeycloakServiceFactory()
    #     return cls._instance

    def __init__(self):
        super().__init__()
        self.register_services()

    @classmethod
    def get_instance(cls) -> 'IamKeycloakServiceFactory':
        if cls._instance is None:
            cls._instance = IamKeycloakServiceFactory()
        return cls._instance

    def register_services(self):
        self.get_service_locator().register(IIamService, KeycloakIamService(self))
        return self

    def get_iam_service(self) -> IIamService:
        return self.get_service_locator().get(IIamService)

    def get_authentication_backend(self):
        return KeycloakOpenIDAuthBackend()

    def get_repository_factory(self) -> IRepositoryFactory:
        """Create and return an IRepositoryFactory instance."""
        return KCDBFactory.get_instance()
