from __future__ import annotations

from logging import Logger

from advanced_alchemy.base import ModelProtocol
from advanced_alchemy.repository import SQLAlchemyAsyncRepository


class KeycloakBaseRepository[T: ModelProtocol](SQLAlchemyAsyncRepository[T]):  # type: ignore[type-arg]
    _logger: Logger

    @property
    def logger(self) -> Logger:
        if not hasattr(self, '_logger'):
            from foundation.observability.log_factory import LogFactory

            self._logger = LogFactory().get_logger(self.__class__.__name__)
        return self._logger
