from abc import ABC, abstractmethod

from foundation.messaging.types import MessageRoutingServiceT
from foundation.resiliant.dlq import IDLQService
from foundation.resiliant.idempotency import IIdempotencyService
from foundation.resiliant.outbox import IOutboxService, ITransactionOutboxService, OutboxTarget
from foundation.resiliant.retry import IRetryPolicyFactory
from foundation.resiliant.saga import ISagaService
from foundation.resiliant.schedule import IScheduleService


class ResiliantServiceFactoryT(ABC):
    """
    This is an abstract base class that defines the interface for creating resiliant services.
    """

    def __init__(self):
        super().__init__()

    @abstractmethod
    def get_messaging_outbox_service(self) -> IOutboxService:
        """
        Return the messaging outbox: domain events published to the broker.
        """
        ...

    @abstractmethod
    def get_transaction_outbox_service(
        self, target: OutboxTarget = OutboxTarget.MESSAGING
    ) -> ITransactionOutboxService:
        """
        Return the transaction outbox: inbound transaction requests relayed to ``target``.
        """
        ...

    def get_outbox_service(self) -> IOutboxService:
        """
        Alias of :meth:`get_messaging_outbox_service` (the default outbox).
        """
        return self.get_messaging_outbox_service()

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
    def get_saga_service(self) -> ISagaService:
        """
        Return a durable (database-backed) SagaService.
        """
        ...

    @abstractmethod
    def get_retry_policy_factory(self) -> IRetryPolicyFactory:
        """
        Return the factory foundation code uses to create retry policies.
        """
        ...

    @abstractmethod
    def get_schedule_service(self) -> IScheduleService:
        """
        Return the durable-timer / scheduler service.
        """
        ...
