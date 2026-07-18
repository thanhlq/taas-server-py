from foundation.http import BaseController

from .controllers._test_controller_demo import TestController
from .repos import RepoFactory


def get_project_controllers() -> list[BaseController]:
    """
    Get the list of project controllers.
    """
    project_controllers: list[BaseController] = [
        TestController(),
    ]
    return project_controllers


__all__ = [
    'get_project_controllers',
    'RepoFactory',
]
