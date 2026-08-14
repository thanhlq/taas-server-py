from foundation import BaseService
from foundation.messaging.message_routing_service import MessageRoutingService
from foundation.messaging.types import MessageRoutingServiceT
from foundation.resiliant.dlq import IDLQService
from foundation.resiliant.idempotency import IIdempotencyService
from foundation.resiliant.outbox import IOutboxService
from foundation.resiliant.saga import SagaService
from foundation.resiliant.schedule import IScheduleService
from foundation.resiliant.types import ResiliantServiceFactoryT
from foundation.utils.singleton import singleton

from resiliant.outbox.outbox_settings import get_outbox_config
from resiliant.service_builder import ResiliantServiceBuilder


@singleton
class ResiliantServiceFactory(BaseService, ResiliantServiceFactoryT):

    def __init__(self):
        super().__init__()
        self._outbox_service: IOutboxService | None = None
        self._dlq_service: IDLQService | None = None
        self._idempotency_service: IIdempotencyService | None = None
        self._message_routing_service: MessageRoutingServiceT | None = None
        self._saga_service: SagaService | None = None
        self._schedule_service: IScheduleService | None = None

    def get_outbox_service(self) -> IOutboxService:
        """
        Return an instance of OutboxService.
        """
        if self._outbox_service is None:
            self._outbox_service = ResiliantServiceBuilder.build_outbox_service()
        return self._outbox_service

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

    def get_saga_service(self) -> SagaService:
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
