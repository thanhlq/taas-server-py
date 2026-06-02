from platform_core.http import BaseController

from .accounts import account_controllers

iam_controllers: list[BaseController | type[BaseController]] = [
    *account_controllers,
]

__all__ = ['iam_controllers']
