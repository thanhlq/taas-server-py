from abc import ABC, abstractmethod

from foundation import BaseService
from foundation.resiliant.idempotency import IIdempotencyService
from foundation.resiliant.outbox import IOutboxService
from foundation.resiliant.dlq import IDLQService


class ResiliantServiceFactoryT(BaseService, ABC):
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
