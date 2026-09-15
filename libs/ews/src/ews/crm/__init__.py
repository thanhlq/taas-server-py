from foundation.http import BaseController

from .controllers import CrmAccountController
from .repos import RepoFactory


def get_crm_controllers() -> list[BaseController]:
    """Get the list of CRM controllers."""
    return [CrmAccountController()]


__all__ = ['RepoFactory', 'get_crm_controllers', 'CrmAccountController']
