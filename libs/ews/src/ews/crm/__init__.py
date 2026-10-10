from foundation.http import BaseController

from .controllers import CrmAccountController, CrmContactController
from .repos import RepoFactory


def get_crm_controllers() -> list[BaseController]:
    """Get the list of CRM controllers."""
    # static paths (``/lead-sources``) are declared before ``/{contact_id}`` in their controller
    return [CrmAccountController(), CrmContactController()]


__all__ = [
    'RepoFactory',
    'get_crm_controllers',
    'CrmAccountController',
    'CrmContactController',
]
