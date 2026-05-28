from platform_core.http import BaseController
from .domain.project import project_controllers

ews_conrrollers: list[type[BaseController]] = [
    *project_controllers,
]

__all__ = [
    'ews_conrrollers',
]
