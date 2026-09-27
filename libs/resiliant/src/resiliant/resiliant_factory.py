from foundation import BaseService
from foundation.messaging.message_routing_service import MessageRoutingService
from foundation.messaging.types import MessageRoutingServiceT
from foundation.resiliant.dlq import IDLQService
from foundation.resiliant.idempotency import IIdempotencyService
from foundation.resiliant.outbox import IOutboxService, ITransactionOutboxService, OutboxTarget
from foundation.resiliant.retry import IRetryPolicyFactory
from foundation.resiliant.saga import ISagaService
from foundation.resiliant.schedule import IScheduleService
from foundation.resiliant.types import ResiliantServiceFactoryT
from foundation.utils.singleton import singleton

from resiliant.outbox.outbox_settings import get_outbox_config
from resiliant.service_builder import ResiliantServiceBuilder


@singleton
class ResiliantServiceFactory(BaseService, ResiliantServiceFactoryT):

    def __init__(self):
        super().__init__()
        self._messaging_outbox_service: IOutboxService | None = None
        self._transaction_outbox_services: dict[OutboxTarget, ITransactionOutboxService] = {}
        self._dlq_service: IDLQService | None = None
        self._idempotency_service: IIdempotencyService | None = None
        self._message_routing_service: MessageRoutingServiceT | None = None
        self._saga_service: ISagaService | None = None
        self._retry_policy_factory: IRetryPolicyFactory | None = None
        self._schedule_service: IScheduleService | None = None

    def get_messaging_outbox_service(self) -> IOutboxService:
        """
        The messaging outbox (``resiliant_outbox_messages``): domain events for the broker.
        ``get_outbox_service()`` is an alias.
        """
        if self._messaging_outbox_service is None:
            self._messaging_outbox_service = ResiliantServiceBuilder.build_messaging_outbox_service()
        return self._messaging_outbox_service

    def get_transaction_outbox_service(
        self, target: OutboxTarget = OutboxTarget.MESSAGING
    ) -> ITransactionOutboxService:
        """
        The transaction outbox (``resiliant_outbox_transactions``) relaying inbound
        transaction requests to ``target`` (one cached service per target).
        """
        if target not in self._transaction_outbox_services:
            self._transaction_outbox_services[target] = (
                ResiliantServiceBuilder.build_transaction_outbox_service(target)
            )
        return self._transaction_outbox_services[target]

    def get_message_routing_service(self) -> MessageRoutingServiceT:
        """
        Return an instance of MessageRoutingService.
        """
        if self._message_routing_service is None:
            self._message_routing_service = MessageRoutingService(get_outbox_config())
        return self._message_routing_service

    def get_dlq_service(self) -> IDLQService:
        """
        Return an instance of DLQService.
        """
        if self._dlq_service is None:
            self._dlq_service = ResiliantServiceBuilder.build_dlq_service()
        return self._dlq_service

    def get_idempotency_service(self) -> IIdempotencyService:
        """
        Return an instance of IdempotencyService.
        """
        if self._idempotency_service is None:
            self._idempotency_service = (
                ResiliantServiceBuilder.build_idempotency_service()
            )
        return self._idempotency_service

    def get_saga_service(self) -> ISagaService:
        """
        Return a durable (database-backed) SagaService.
        """
        if self._saga_service is None:
            self._saga_service = ResiliantServiceBuilder.build_saga_service()
        return self._saga_service

    def get_schedule_service(self) -> IScheduleService:
        """
        Return the durable-timer / scheduler service.
        """
        if self._schedule_service is None:
            self._schedule_service = ResiliantServiceBuilder.build_schedule_service()
        return self._schedule_service

    def get_retry_policy_factory(self) -> IRetryPolicyFactory:
        """
        Factory of retry policies (Tenacity) used by foundation code, e.g. the
        messaging event processors.
        """
        if self._retry_policy_factory is None:
            from resiliant.retry import TenacityRetryPolicyFactory

            self._retry_policy_factory = TenacityRetryPolicyFactory()
        return self._retry_policy_factory
