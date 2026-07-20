from abc import ABC, abstractmethod

from db.common import IRepositoryFactory
from starlette.authentication import AuthenticationBackend

from iam.auth.types import IamDirectoryServiceT, IamDirectorySignupServiceT


class IIamServiceFactory(ABC):
    """
    Factory for creating of related IIamService services.
    These services are normally implemented by real iam platforms as Keycloak, Auth0,....
    """

    @abstractmethod
    def get_authentication_backend(self) -> AuthenticationBackend:
        """Used for integration with fastapi authentication system.
        Normally installed in the middleware."""
        ...

    @abstractmethod
    def get_directory_service(self) -> IamDirectoryServiceT:
        """
        Get the directory service instance which is responsible for managing users, groups, and other directory-related operations (e.g., Keycloak, Auth0).
        """
        ...

    @abstractmethod
    def get_directory_signup_service(self) -> IamDirectorySignupServiceT:
        """
        Get the directory signup service instance which is responsible for handling user signup and related operations (e.g., Keycloak, Auth0).
        """
        ...

    @abstractmethod
    def get_directory_repository_factory(self) -> IRepositoryFactory: ...
    """ Create and return an IRepositoryFactory instance for the actual directory platform (i.e. linked to keycloak DB)."""
