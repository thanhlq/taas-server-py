from platform_core.http import BaseController

from ews.domain.platform.controller._platform import PlatformController

from .domain.ppm import project_controllers

conrrollers: list[type[BaseController] | BaseController] = [
    *project_controllers,
    PlatformController(),
]

__all__ = [
    'conrrollers',
]
