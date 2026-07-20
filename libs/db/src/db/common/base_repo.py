from __future__ import annotations

from logging import Logger

from advanced_alchemy.base import ModelProtocol
from advanced_alchemy.repository import (
    ModelT,
    SQLAlchemyAsyncRepository,
)
from sqlalchemy.ext.asyncio import AsyncSession


class BaseAsyncRepository[T: ModelProtocol](SQLAlchemyAsyncRepository[T]):  # type: ignore[type-arg]
    """
    All the repositories should inherit from this class to ensure consistent logging and behavior across the application.
    """
    _logger: Logger

    @property
    def logger(self) -> Logger:
        if not hasattr(self, '_logger'):
            from foundation.observability.log_factory import LogFactory

            self._logger = LogFactory().get_logger(self.__class__.__name__)
        return self._logger


__all__ = ['BaseAsyncRepository', 'ModelT', 'AsyncSession']
