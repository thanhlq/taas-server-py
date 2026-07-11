from foundation.messaging.types import IMessagingService
from foundation.resiliant.outbox import IOutboxPublisher
from foundation.state import get_service


class OutboxPublisher(IOutboxPublisher):
    """
    Publisher for outbox events.
    """

    def get_messaging_service(self) -> IMessagingService:
        return get_service(IMessagingService)
