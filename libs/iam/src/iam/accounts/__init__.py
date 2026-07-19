from .controllers._account import AccountController


def get_account_controllers() -> list:
    """Return a list of all auth controllers."""
    account_controllers = [AccountController()]
    return account_controllers


__all__ = ['get_account_controllers']
