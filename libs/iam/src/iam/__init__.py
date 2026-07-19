from foundation.http import BaseController


def get_iam_controllers() -> list[BaseController | type[BaseController]]:
    """
    Get the list of IAM controllers.
    """
    from .accounts import get_account_controllers
    from .auth import get_auth_controllers


    return [*get_auth_controllers(), *get_account_controllers()]

__all__ = ['get_iam_controllers']
