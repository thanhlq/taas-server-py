from platform_core.http import BaseController
from .controllers._project_controller import ProjectController

project_controllers: list[BaseController] = [
    ProjectController(),
]

__all__ = [
    "project_controllers",
]
