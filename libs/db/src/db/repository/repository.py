from __future__ import annotations

import inspect
from typing import TypeVar

from advanced_alchemy.base import ModelProtocol

from .types import IAsyncRepository, IRepositoryFactory

ModelT = TypeVar('ModelT', bound=ModelProtocol)


class RepositoryFactory(IRepositoryFactory):
    # _repositories: dict[type[ModelT], IRepository]
    _repositories_async: dict

    def __init__(self):
        self._repositories = {}
        self._repositories_async = {}

    # def add(self, model_cls: type[ModelT], repository: IRepository) -> RepositoryFactory:
    #     self._repositories[model_cls] = repository
    #     return self

    # def get(self, model_cls: type[ModelT]) -> IRepository:
    #     repo_class = self._repositories[model_cls]
    #     if not repo_class:
    #         raise ValueError(f'Unknown repository type: {model_cls}')

    #     # Normally the repo classes are cheap to instantiate whenever needed
    #     if inspect.isclass(repo_class):
    #         return repo_class(self)
    #     else:
    #         return repo_class

    def add_async(
        self, model_cls: type[ModelT], repository: IAsyncRepository
    ) -> 'IRepositoryFactory':
        self._repositories_async[model_cls] = repository
        return self

    def get_async(self, model_cls: type[ModelT]) -> IAsyncRepository:
        try:
            repo_class = self._repositories_async[model_cls]
            if not repo_class:
                raise ValueError(f'Unknown async repository type: {model_cls}')

                # Normally the repo classes are cheap to instantiate whenever needed

            if inspect.isclass(repo_class):
                return repo_class(self)
            else:
                return repo_class
        except Exception as e:
            # print(f"Error getting async repository for {model_cls.__class__.name}: {e}")
            # raise ValueError(f"Unknown async repository type: {model_cls.__class__.name}")
            raise e
