"""core service types"""

from logging import Logger
from typing import TYPE_CHECKING

from foundation.facade.cache import CacheServiceT
from foundation.state import get_service as registry_get_service

if TYPE_CHECKING:
    from foundation.messaging.types import IMessagingService
    from foundation.resiliant.types import ResiliantServiceFactoryT


class BaseService:
    _logger: Logger | None = None
    _resiliant_factory: ResiliantServiceFactoryT | None = None

    @property
    def logger(self) -> Logger:
        if self._logger is None:
            self._logger = Logger(self.__class__.__name__)
        return self._logger

    async def start(self) -> 'BaseService':
        return self

    async def stop(self):
        self._resiliant_factory = None
        pass

    def get_service[T](self, t: type[T]) -> T:
        return registry_get_service(t)

    @property
    def cache_service(self) -> CacheServiceT:
        return registry_get_service(CacheServiceT)

    @property
    def messaging_service(self) -> IMessagingService:
        return registry_get_service(IMessagingService)

    @property
    def message_routing_service(self):
        return self.resiliant_factory.get_message_routing_service()


    @property
    def resiliant_factory(self) -> 'ResiliantServiceFactoryT':
        if self._resiliant_factory is None:
            self._resiliant_factory = registry_get_service(ResiliantServiceFactoryT)

        return self._resiliant_factory
