""" A factory class for instantiating the Auth related classes. """
from platform_core.state import get_service
from iam.auth.types import IamDirectoryServiceT


from platform_core.db.types import DBAsyncScopedSession, DBAsyncSession

from iam.accounts.services._users import UserService


class AuthFactory:

    @staticmethod
    def get_directory_service() -> IamDirectoryServiceT:
        return get_service(IamDirectoryServiceT)
