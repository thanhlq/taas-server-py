"""core service types"""

from logging import Logger
from typing import TYPE_CHECKING

from foundation.state import get_service

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

    @property
    def messaging_service(self):
        return get_service(IMessagingService)

    @property
    def resiant_factory(self) -> 'ResiliantServiceFactoryT':
        if self._resiliant_factory is None:
            self._resiliant_factory = get_service(ResiliantServiceFactoryT)

        return self._resiliant_factory
