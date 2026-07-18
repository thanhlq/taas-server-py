from foundation.messaging.events.event_handler import BaseEventHandler
from foundation.messaging.types import BaseEvent, EventMetadata, ProcessingResult

from iam.auth.auth_events import TenantCreatedEvent
from iam.iam_constants import IamEvents


class TenantSetupEventHandler(BaseEventHandler[TenantCreatedEvent]):
    """
    Handler to process tenant preparation.
    """

    def __init__(self, **kwargs):
        super().__init__(TenantCreatedEvent, **kwargs)

    async def handle(self, event: BaseEvent, meta: EventMetadata,  **kwargs) -> ProcessingResult:
        # TODO: Implement tenant created email sending logic
        self.logger.warning(
            f'🧪 TenantSetupEventHandler not implemented yet: event_id={meta.event_id}'
        )

        # print_dict_pretty(event.as_dict(), 'TenantCreatedEvent payload')

        raise NotImplementedError('🧪 TenantSetupEventHandler not implemented yet')

    async def validate(self, event: BaseEvent, meta: EventMetadata,  **kwargs) -> bool:
        return event.event_type == IamEvents.TENANT_CREATED
