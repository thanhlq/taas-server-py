from foundation.messaging.types import BaseEvent, EventMetadata, ProcessingResult

from iam.auth.auth_events import UserRegisteredEvent
from iam.common.base import BaseIamEventHandler
from iam.iam_constants import IamEvents


class IamWelcomeAccountNotificationHandler(BaseIamEventHandler[UserRegisteredEvent]):
    def __init__(self, **kwargs):
        super().__init__(UserRegisteredEvent, **kwargs)

    async def handle_event(
        self,
        event: UserRegisteredEvent,
        meta: EventMetadata,
        **kwargs,
    ) -> ProcessingResult:

        # print_dict_pretty(event.as_dict(), 'UserRegisteredEvent payload')
        self.logger.info(
            f'📧 🧪 Sending welcome email to {event.email} for new user registration...'
        )

        directory_service = self.directory_service

        await directory_service.signup_send_welcome_email(event)

        return ProcessingResult(
            event_id=event.event_id,
            retry_count=event.retry_count,
            success=True,
            message='Welcome email sent',
        )

    async def validate(self, event: BaseEvent, meta: EventMetadata, **kwargs) -> bool:
        return event.event_type == IamEvents.USER_REGISTERED
