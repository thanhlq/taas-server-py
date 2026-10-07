from typing import Final

from foundation.app.types import ApiApplicationModuleT
from foundation.http import BaseController
from foundation.messaging.events.event_handler import EventStep
from foundation.messaging.events.flow_registration import event_type_value
from foundation.messaging.types import BaseEvent
from foundation.utils.singleton import singleton

from iam.auth.handlers.auth_event_flows import USER_ONBOARDING
from iam.iam_constants import IamEvents, get_iam_topic_for_event


def get_iam_controllers() -> list[BaseController | type[BaseController]]:
    """
    Get the list of IAM controllers.
    """
    from .auth import get_auth_controllers

    # The legacy user CRUD (`iam.accounts`, `/api/v1/users`) is not mounted: it had no authentication, and users
    # are managed by the TaaS IAM admin API (taas-server-js, taas-specs/admin/admin-iam-api.md).
    return [*get_auth_controllers()]


# ---------------------------------------------------------------------------
# Registry of all IAM flows
# ---------------------------------------------------------------------------

IAM_ALL_FLOWS: Final[dict[str, tuple[EventStep, ...]]] = {
    'user_onboarding': USER_ONBOARDING,
}


@singleton
class IamApplicationModule(ApiApplicationModuleT):
    """
    Iam application module
    """

    def get_api_controllers(self) -> list[BaseController | type[BaseController]]:
        return get_iam_controllers()

    def get_event_flows(self) -> dict[str, tuple[EventStep, ...]]:
        return IAM_ALL_FLOWS

    def get_topic_for_event(self, event_cls: type[BaseEvent]) -> str:
        return get_iam_topic_for_event(IamEvents(event_type_value(event_cls)))
