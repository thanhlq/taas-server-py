from foundation.messaging.types import MessagingServiceT
from foundation.resiliant.outbox import IOutboxPublisher
from foundation.state import get_service


class OutboxPublisher(IOutboxPublisher):
    """
    Publisher for outbox events.
    """

    def get_messaging_service(self) -> MessagingServiceT:
        return get_service(MessagingServiceT)
