""" A factory class for instantiating the Auth related classes. """
from foundation.state import get_service
from iam.auth.types import IamDirectoryServiceT





class AuthFactory:

    @staticmethod
    def get_directory_service() -> IamDirectoryServiceT:
        return get_service(IamDirectoryServiceT)
