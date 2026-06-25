from core.db.repository import RepositoryFactory

from ..domains.entities import KeycloakUser
from .repositories.kc_directory_user_repo import DirectoryUserRepository


class KCDBFactory(RepositoryFactory):
    """
    Factory for IAM-related repositories.
    This class extends the RepositoryFactory to provide specific IAM repositories.
    """

    _instance: 'KCDBFactory | None' = None

    def __new__(cls):
        """Ensure singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize the factory only once."""
        if not hasattr(self, '_initialized'):
            super().__init__()
            self.add_async(KeycloakUser, DirectoryUserRepository)
            self._initialized = True

    @classmethod
    def get_instance(cls) -> 'KCDBFactory':
        """Get the singleton instance of IamDBFactory."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
