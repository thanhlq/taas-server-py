from db.common import RepositoryFactory

from ..domains.entities import KeycloakUser
from .repositories.kc_user_repo import KeycloakUserRepository


class KeycloakRepositoryFactory(RepositoryFactory):
    def __init__(self):
        """
        Providing database repository for the Keycloak underling database.
        """
        if not hasattr(self, '_initialized'):
            super().__init__()
            self.add_async(KeycloakUser, KeycloakUserRepository)
            self._initialized = True
