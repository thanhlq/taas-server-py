""" A factory class for instantiating the Account related classes. """


from foundation.db.types import DBAsyncScopedSession, DBAsyncSession

from iam.accounts.services._users import UserService


class UserAccountFactory:

    @staticmethod
    def get_user_service(session: DBAsyncSession | DBAsyncScopedSession) -> UserService:
        return UserService(session)
