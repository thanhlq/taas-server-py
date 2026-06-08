from platform_core.http import BaseController

from .controllers._test_controller_demo import TestController

project_controllers: list[BaseController] = [
    TestController(),
]

__all__ = [
    "project_controllers",
]
