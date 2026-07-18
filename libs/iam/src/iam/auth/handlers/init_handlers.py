# IAM domain wiring for the generic flow-driven registration in
# ``core.events.flow_registration``.
#
# 🔑 Single source of truth: ``core.iam.events.iam_event_flows.IAM_ALL_FLOWS``.
#    Both handler registration and schema-registry registration are *derived*
#    from those flow definitions, so adding a new step in ``iam_event_flows.py``
#    is the only change required to wire a new IAM handler / event / schema.
from typing import Any

from foundation.messaging.events.event_handler import HandlerRegistry, handlerRegistry
from foundation.messaging.events.flow_registration import (
    event_type_value,
    register_handlers_from_flows,
    register_schema_registry_schemas,
)
from foundation.messaging.types import (
    BaseEvent,
    IMessagingDecorators,
    IMessagingService,
)

from iam.auth.auth_events import UserDirectoryCreatedEvent, UserRegisteredEvent
from iam.auth.handlers.iam_event_flows import IAM_ALL_FLOWS
from iam.iam_constants import IamEvents, IamTopics, get_topic_for_event

# Re-exports kept for tests / external imports that still reference them.
from .internal_user_setup_handler import InternalUserSetupHandler
from .tenant_setup_handler import TenantSetupEventHandler
from .welcome_email_handler import IamWelcomeAccountNotificationHandler

__all__ = [
    'InternalUserSetupHandler',
    'TenantSetupEventHandler',
    'IamWelcomeAccountNotificationHandler',
    'register_iam_handlers',
    'register_iam_schema_registry_schemas',
    'register_handler_by_decorator',
]


def _iam_topic_for_event(event_cls: type[BaseEvent]) -> str:
    """Resolve an event class to its IAM Kafka topic, or ``None`` if it's
    not an IAM event (event_type not in the ``IamEvents`` enum)."""
    return get_topic_for_event(IamEvents(event_type_value(event_cls)))


def register_iam_schema_registry_schemas(msg_service: IMessagingService) -> None:
    """Register Avro schemas for every topic referenced by IAM flows."""
    # Imported here, not at module level: iam_event_flows imports the handler
    # classes from this package, so a top-level back-import is circular.

    register_schema_registry_schemas(
        msg_service, flows=IAM_ALL_FLOWS, topic_for_event=_iam_topic_for_event,
    )


def register_iam_handlers(
    registry: HandlerRegistry = handlerRegistry,
    *,
    msg_service: IMessagingService,
) -> None:
    """Register IAM event handlers from ``IAM_ALL_FLOWS`` into ``registry``."""
    # See register_iam_schema_registry_schemas for why this import is deferred.

    register_handlers_from_flows(
        flows=IAM_ALL_FLOWS,
        msg_service=msg_service,
        topic_for_event=_iam_topic_for_event,
        registry=registry,
        domain_label='IAM',
    )


# Testing only
def register_handler_by_decorator(decorator: IMessagingDecorators) -> None:
    """Register handlers using the provided decorator."""

    print('✅  Registering handlers using decorator...')

    @decorator.subscriber(topic=IamTopics.IAM_USER_REGISTER, group_id='test-group')
    async def handle_user_directory_created(event: UserDirectoryCreatedEvent, _message: Any) -> None:
        print('---------------------------')
        print(f'✅ [handle_user_directory_created] Handling, event type {event.event_type}, event id {event.event_id} with decorated handler...')
        print('---------------------------')

    @decorator.subscriber(topic=IamTopics.IAM_USER_REGISTER, group_id='test-group')
    async def handle_user_created(event: UserRegisteredEvent, _message: Any) -> None:
        print('---------------------------')
        print(f'✅ [handle_user_created] Handling, event type {event.event_type}, event id {event.event_id} with decorated handler...')
        print('---------------------------')
