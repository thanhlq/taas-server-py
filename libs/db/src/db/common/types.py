from __future__ import annotations

from abc import abstractmethod

from advanced_alchemy.base import ModelProtocol
from advanced_alchemy.extensions.fastapi import repository


class IAsyncRepository[ModelT: ModelProtocol](
    repository.SQLAlchemyAsyncRepository[ModelT]
):
    pass


class IRepositoryFactory[ModelT: ModelProtocol]:
    """
    Factory Pattern: Define a stateless repositories (Single Responsibility Principle better)
    """

    # @abstractmethod
    # def add(
    #     self, model_cls: type[ModelT], repository: IRepository
    # ) -> 'IRepositoryFactory':
    #     """Adds a synchronous repository for the given model type."""
    #     ...

    # @abstractmethod
    # def get(self, model_cls: type[ModelT]) -> IRepository:
    #     """Retrieves a synchronous repository for the given model type."""
    #     ...

    @abstractmethod
    def add_async(
        self, model_cls: type[ModelT], repository: IAsyncRepository
    ) -> 'IRepositoryFactory':
        """Adds a async repository for the given model type."""
        ...

    @abstractmethod
    def get_async(self, model_cls: type[ModelT]) -> IAsyncRepository:
        """Retrieves a async repository for the given model type."""
        ...
