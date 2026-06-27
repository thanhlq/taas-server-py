from platform_core.db.types import DBAsyncSession, DBAsyncScopedSession
from ._user_repo import UserRepository

__all__ = ['UserRepository']


class RepoFactory:
    """Factory for creating repository instances."""

    @staticmethod
    def user_repo() -> type[UserRepository]:
        """Create a new instance of UserRepository."""
        return UserRepository

    @staticmethod
    def get_user_repo(session: DBAsyncSession | DBAsyncScopedSession) -> UserRepository:
        """Get an instance of UserRepository."""
        return UserRepository(session=session)

