from abc import ABC, abstractmethod

from foundation.messaging.types import MessageRoutingServiceT
from foundation.resiliant.dlq import IDLQService
from foundation.resiliant.idempotency import IIdempotencyService
from foundation.resiliant.outbox import IOutboxService
from foundation.resiliant.saga import SagaService
from foundation.resiliant.schedule import IScheduleService


class ResiliantServiceFactoryT(ABC):
    """
    This is an abstract base class that defines the interface for creating resiliant services.
    """

    def __init__(self):
        super().__init__()

    @abstractmethod
    def get_outbox_service(self) -> IOutboxService:
        """
        Return an instance of OutboxService.
        """
        ...

    @abstractmethod
    def get_message_routing_service(self) -> MessageRoutingServiceT:
        """
        Return an instance of MessageRoutingService.
        """
        ...

    @abstractmethod
    def get_dlq_service(self) -> IDLQService:
        """
        Return an instance of DLQService.
        """
        ...

    @abstractmethod
    def get_idempotency_service(self) -> IIdempotencyService:
        """
        Return an instance of IdempotencyService.
        """
        ...

    @abstractmethod
    def get_saga_service(self) -> SagaService:
        """
        Return a durable (database-backed) SagaService.
        """
        ...

    @abstractmethod
    def get_schedule_service(self) -> IScheduleService:
        """
        Return the durable-timer / scheduler service.
        """
        ...
