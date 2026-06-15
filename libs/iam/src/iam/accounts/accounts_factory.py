""" A factory class for instantiating the Account related classes. """


from platform_core.db.types import DBAsyncScopedSession, DBAsyncSession

from iam.accounts.services._users import UserService


class AccountFactory:

    @staticmethod
    def get_user_service(session: DBAsyncSession | DBAsyncScopedSession) -> UserService:
        return UserService(session)
