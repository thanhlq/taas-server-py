from foundation.http import BaseController

from ews.platform.controller._platform import PlatformController

from .ppm import project_controllers

conrrollers: list[type[BaseController] | BaseController] = [
    *project_controllers,
    PlatformController(),
]

__all__ = [
    'conrrollers',
]
