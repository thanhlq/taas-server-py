from foundation.http import BaseController

from ews.platform.controller._platform import PlatformController

from .crm import get_crm_controllers
from .ppm import get_project_controllers


def get_ews_controllers() -> list[type[BaseController] | BaseController]:
    """
    Get the list of EWS controllers.
    """
    controllers: list[type[BaseController] | BaseController] = [
        *get_project_controllers(),
        *get_crm_controllers(),
        PlatformController(),
    ]
    return controllers


__all__ = [
    'get_ews_controllers',
]
