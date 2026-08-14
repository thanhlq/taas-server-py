# from foundation.db.sa.db_manager import MainDBManager
from typing import Any, Optional

from foundation import BaseService
from foundation.cli import cli
from foundation.db.advanced_db_manager import MainDatabase
from foundation.db.types import DBAsyncScopedSession, DBAsyncSession
from foundation.messaging.base_messaging import BaseEvent
from foundation.resiliant.outbox import IOutboxService, OutboxConfig
from foundation.state import get_service
from foundation.utils.singleton import singleton

from .types import BaseSendableMessage, MessageRoutingServiceT, MessagingServiceT


@singleton
class MessageRoutingService(BaseService, MessageRoutingServiceT):
    """
    A service that routes messages either through the outbox pattern or directly to the messaging service based on configuration.
    """

    _messaging_service: Optional[MessagingServiceT]
    _outbox_service: Optional[IOutboxService]
    _outbox_config: OutboxConfig

    def __init__(
        self,
        outbox_config: OutboxConfig,
        messaging_service: Optional[MessagingServiceT] = None,
        outbox_service: Optional[IOutboxService] = None,
    ):
        super().__init__()

        self._messaging_service = messaging_service
        self._outbox_service = outbox_service
        self._outbox_config = outbox_config

        init_info: dict[str, Any] = {
            "outbox_enabled": self._outbox_config.enabled,
            "default_routing": self._outbox_config.routing_default,
            "direct_channels": list(self._outbox_config.direct_channels.keys()),
            "outbox_channels": list(self._outbox_config.outbox_channels.keys()),
        }
        cli.info_table(
            title="Message Routing Service Configuration",
            data=init_info,
        )

        self.logger.info(
            '📦 MessageRoutingService initialized', init_info
        )

    def get_config(self) -> OutboxConfig:
        return self._outbox_config

    @property
    def outbox_enabled(self) -> bool:
        return self._outbox_config.enabled

    @property
    def messaging_service(self) -> MessagingServiceT:
        if not self._messaging_service:
            self._messaging_service = get_service(MessagingServiceT)

        return self._messaging_service

    @property
    def outbox_service(self) -> IOutboxService:
        if not self._outbox_service:
            self._outbox_service = get_service(IOutboxService, True)

        return self._outbox_service

    def validate(self):
        if not self.outbox_enabled and not self.messaging_service:
            raise ValueError(
                'Messaging service must be provided when outbox is disabled'
            )

    async def publish_event(
        self,
        event: BaseSendableMessage,
        channel: str,
        *,
        session: DBAsyncSession | DBAsyncScopedSession | None = None,
        ordering_key: str | None = None,
        headers: dict[str, Any] | None = None,
        max_retries: int | None = None,
    ) -> Any:
        """
        Save domain event to outbox or publish directly based on configuration.

        If outbox is enabled: Saves to database for reliable async publishing
        If outbox is disabled: Publishes immediately to messaging provider

        Args:
            session: Database session (used only when outbox is enabled)
            event: Domain event to publish
            channel: Channel name (topic/stream/queue)
            ordering_key: Optional ordering key for Kafka
            headers: Optional message headers
            max_retries: Override default max retries (outbox only)

        Returns:
            OutboxEvent if outbox enabled, None if direct publish
        """

        if isinstance(event, BaseEvent):
            print(f'MessageRoutingService.publish_event: event_type={event.event_type}, event_id={event.event_id}, m_serializer={event.m_serializer}, timestamp={event.timestamp}')
            # event.validate_event()  # ensure required fields are present

        if self.get_routing_for_channel(channel) == "outbox":
            _new_session = None
            if session is None:
                # in event / user directory creation case, we don't have a db session, but we still want to use outbox to ensure reliable delivery
                self.logger.warning(
                    '🐬 ⚠️ Outbox is enabled but no database session provided. '
                    'This may lead to issues with transactional guarantees.'
                )
                _new_session = MainDatabase.get_instance().new_session()

            self.logger.info(f'🚦📤 Saving event to outbox: {event.__class__.__name__} → {channel}, event type: {getattr(event, "event_type", "N/A")}, event id: {getattr(event, "event_id", "N/A")}')
            result = await self.outbox_service.save_event(
                session=_new_session or session,
                event=event,
                channel=channel,
                ordering_key=ordering_key,
                headers=headers,
                max_retries=max_retries,
            )
            if _new_session:
                await _new_session.commit()
                await _new_session.close()
            return result
        else:
            # Direct publish (no transactional guarantee)
            self.logger.debug(
                f'Publishing event directly: {event.__class__.__name__} → {channel}'
            )
            await self.messaging_service.publish(
                channel=channel,
                message=event,
                headers=headers,
                ordering_key=ordering_key,
            )
            return None

