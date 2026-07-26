from foundation.messaging.types import BaseEvent, EventMetadata, ProcessingResult

from iam.admin.services import get_admin_service
from iam.auth.auth_events import (
    IamEvents,
    UserDirectoryCreatedEvent,
)
from iam.common.base import BaseIamEventHandler


class InternalUserSetupHandler(BaseIamEventHandler[UserDirectoryCreatedEvent]):
    """
    Handler to process internal user setup after directory user creation.
    """

    def __init__(self, **kwargs):
        super().__init__(event_class=UserDirectoryCreatedEvent, **kwargs)

    async def handle_event(
        self,
        event: BaseEvent,
        meta: EventMetadata,
        **kwargs,
    ) -> ProcessingResult:
        return await self._handle_event(event, meta, **kwargs)

    # @db_context_session(auto_commit=True)
    async def _handle_event(
        self, event: BaseEvent, meta: EventMetadata, **kwargs
    ) -> ProcessingResult:
        result = self.validate_event(event, meta)
        if result is not None:
            return result

        _directory_user = event.get_payload().user
        _directory_tenant = event.get_payload().tenant

        admin_service = get_admin_service()
        await admin_service.create_root_account_from_directory(
            _directory_user,
            _directory_tenant,
        )

        return ProcessingResult(
            success=True,
            message='Internal user setup completed successfully',
            event_id=event.event_id,
            retry_count=event.retry_count,
        )

    def validate_event(
        self, event: BaseEvent, meta: EventMetadata, **kwargs
    ) -> ProcessingResult | None:
        user_dict = event.get_payload().user
        tenant_dict = event.get_payload().tenant

        if not user_dict:
            self.logger.error(f'Invalid user data in payload: event_id={meta.event_id}')
            return ProcessingResult(
                success=False,
                message='Invalid user data in payload',
                event_id=meta.event_id,
                retry_count=meta.retry_count,
                error='Invalid user data in payload',
            )

        if not tenant_dict:
            self.logger.error(
                f'Invalid tenant data in payload: event_id={meta.event_id}'
            )
            return ProcessingResult(
                success=False,
                message='Invalid tenant data in payload',
                event_id=meta.event_id,
                retry_count=meta.retry_count,
                error='Invalid tenant data in payload',
            )

    async def validate(self, event: BaseEvent, meta: EventMetadata, **kwargs) -> bool:
        return event.event_type == IamEvents.USER_DIRECTORY_CREATED
