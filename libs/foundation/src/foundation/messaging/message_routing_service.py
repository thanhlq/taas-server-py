# from foundation.db.sa.db_manager import MainDBManager
from typing import Any, Dict, Optional

from foundation import BaseService
from foundation.db.advanced_db_manager import MainDatabase
from foundation.resiliant.outbox import IOutboxPublisher, IOutboxService, OutboxConfig
from foundation.state import get_service
from foundation.utils.singleton import singleton

from .types import BaseEvent, IMessagingService


@singleton
class MessageRoutingService(BaseService, IOutboxPublisher):
    """
    A service that routes messages either through the outbox pattern or directly to the messaging service based on configuration.
    """

    _messaging_service: Optional[IMessagingService]
    _outbox_service: Optional[IOutboxService]
    _outbox_config: OutboxConfig

    def __init__(
        self,
        messaging_service: Optional[IMessagingService] = None,
        outbox_service: Optional[IOutboxService] = None,
        outbox_config: Optional[OutboxConfig] = None,
    ):
        super().__init__()

        if outbox_config is None:
            outbox_config = OutboxConfig()

        self._messaging_service = messaging_service
        self._outbox_service = outbox_service
        self._outbox_config = outbox_config
        self.logger.info(
            '📦 MessageRoutingService initialized. Outbox config: %s', outbox_config
        )

    @property
    def outbox_enabled(self) -> bool:
        return self._outbox_config.enabled

    @property
    def messaging_service(self) -> IMessagingService:
        if not self._messaging_service:
            self._messaging_service = get_service(IMessagingService)

        if not self._messaging_service:
            raise ValueError('Messaging service is not available in Service Locator')

        return self._messaging_service

    @property
    def outbox_service(self) -> IOutboxService:
        if not self._outbox_service:
            self._outbox_service = get_service(IOutboxService, True)

        # if not self._outbox_service:
        #     # use default implementation
        #     self._outbox_service = OutboxService(OutboxConfig())

        return self._outbox_service

    def validate(self):
        if not self.outbox_enabled and not self.messaging_service:
            raise ValueError(
                'Messaging service must be provided when outbox is disabled'
            )

    async def save_event(
        self,
        session: Any,  # AsyncSession from SQLAlchemy
        event: BaseEvent,
        channel: str,
        partition_key: Optional[str] = None,
        headers: Optional[Dict[str, Any]] = None,
        max_retries: Optional[int] = None,
    ) -> Any:
        """
        Save domain event to outbox or publish directly based on configuration.

        If outbox is enabled: Saves to database for reliable async publishing
        If outbox is disabled: Publishes immediately to messaging provider

        Args:
            session: Database session (used only when outbox is enabled)
            event: Domain event to publish
            channel: Channel name (topic/stream/queue)
            partition_key: Optional partition key for Kafka
            headers: Optional message headers
            max_retries: Override default max retries (outbox only)

        Returns:
            OutboxEvent if outbox enabled, None if direct publish
        """
        if self.outbox_enabled:
            _new_session = None
            if session is None:
                # in event / user directory creation case, we don't have a db session, but we still want to use outbox to ensure reliable delivery
                self.logger.warning(
                    'Outbox is enabled but no database session provided. '
                    'This may lead to issues with transactional guarantees.'
                )
                _new_session = MainDatabase.get_instance().new_session()
            result = await self.outbox_service.save_event(
                session=_new_session or session,
                event=event,
                channel=channel,
                partition_key=partition_key,
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
                key=partition_key,
            )
            return None

    async def save_raw_message(
        self,
        session: Any,
        channel: str,
        payload: Dict[str, Any],
        event_type: str,
        partition_key: Optional[str] = None,
        headers: Optional[Dict[str, Any]] = None,
        max_retries: Optional[int] = None,
    ) -> Any:
        """
        Save raw message to outbox or publish directly based on configuration.

        If outbox is enabled: Saves to database for reliable async publishing
        If outbox is disabled: Publishes immediately to messaging provider

        Args:
            session: Database session (used only when outbox is enabled)
            channel: Channel name (topic/stream/queue)
            payload: Message payload (will be JSON serialized)
            event_type: Event type identifier
            partition_key: Optional partition key
            headers: Optional message headers
            max_retries: Override default max retries (outbox only)

        Returns:
            OutboxEvent if outbox enabled, None if direct publish
        """
        if self.outbox_enabled:
            # Use transactional outbox pattern
            self.logger.debug(f'Saving raw message to outbox: {event_type} → {channel}')
            return await self.outbox_service.save_raw_message(
                session=session,
                channel=channel,
                payload=payload,
                event_type=event_type,
                partition_key=partition_key,
                headers=headers,
                max_retries=max_retries,
            )
        else:
            # Direct publish (need to convert to BaseEvent-like structure)
            # Note: Direct publishing raw messages requires the messaging service
            # to accept dict payloads. Consider wrapping in a generic event.
            self.logger.warning(
                f'Direct publishing raw message without outbox: {event_type} → {channel}. '
                'This bypasses transactional guarantees and may lose messages on failure.'
            )
            # TODO: Implement direct raw message publishing if messaging_service supports it
            # For now, raise an exception to force using outbox for raw messages
            raise NotImplementedError(
                'Direct publishing of raw messages is not supported. '
                'Please enable outbox or convert to BaseEvent before publishing.'
            )
