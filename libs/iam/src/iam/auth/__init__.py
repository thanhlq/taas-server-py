from .controllers._auth import AuthController


def get_auth_controllers() -> list:
    """Return a list of all auth controllers."""
    account_controllers = [AuthController()]
    return account_controllers


__all__ = ['get_auth_controllers']
