from db.repository import RepositoryFactory

from ..domains.entities import KeycloakUser
from .repositories.kc_user_repo import KeycloakUserRepository


class KCDBFactory(RepositoryFactory):
    def __init__(self):
        """Initialize the factory only once."""
        if not hasattr(self, '_initialized'):
            super().__init__()
            self.add_async(KeycloakUser, KeycloakUserRepository)
            self._initialized = True
