from foundation.messaging.types import BaseEvent, EventMetadata, ProcessingResult

from iam.admin.services import get_admin_service
from iam.auth.auth_events import (
    IamEvents,
    UserDirectoryCreatedEvent,
)
from iam.auth.types import DirectoryTenant, DirectoryUser
from iam.common.base import BaseIamEventHandler


class InternalUserSetupHandler(BaseIamEventHandler[UserDirectoryCreatedEvent]):
    """
    Handler to process internal user setup after directory user creation.
    """

    def __init__(self, **kwargs):
        super().__init__(event_class=UserDirectoryCreatedEvent, **kwargs)

    async def handle_event(
        self,
        event: UserDirectoryCreatedEvent,
        meta: EventMetadata,
        **kwargs,
    ) -> ProcessingResult:
        return await self._handle_event(event, meta, **kwargs)

    # @db_context_session(auto_commit=True)
    async def _handle_event(
        self, event: UserDirectoryCreatedEvent, meta: EventMetadata, **kwargs
    ) -> ProcessingResult:

        user_dict: DirectoryUser = event.user
        tenant_dict: DirectoryTenant = event.tenant

        admin_service = get_admin_service()
        await admin_service.create_root_account_from_directory(
            user_dict,
            tenant_dict,
        )

        return ProcessingResult(
            success=True,
            message='Internal user setup completed successfully',
            event_id=event.event_id,
            retry_count=event.retry_count,
        )

    def validate_event(
        self, event: UserDirectoryCreatedEvent, meta: EventMetadata, **kwargs
    ) -> ProcessingResult | None:
        user_dict: DirectoryUser = event.user
        tenant_dict: DirectoryTenant = event.tenant

        if not user_dict:
            self.logger.error(
                f'Invalid user data in payload: event_id={event.event_id}'
            )
            return ProcessingResult(
                success=False,
                message='Invalid user data in payload',
                event_id=event.event_id,
                retry_count=meta.retry_count,
                error='Invalid user data in payload',
            )

        if not tenant_dict:
            self.logger.error(
                f'Invalid tenant data in payload: event_id={event.event_id}'
            )
            return ProcessingResult(
                success=False,
                message='Invalid tenant data in payload',
                event_id=event.event_id,
                retry_count=meta.retry_count,
                error='Invalid tenant data in payload',
            )

    async def validate(self, event: BaseEvent, meta: EventMetadata, **kwargs) -> bool:
        return event.event_type == IamEvents.USER_DIRECTORY_CREATED
