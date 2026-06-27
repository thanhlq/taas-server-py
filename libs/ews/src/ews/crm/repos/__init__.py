from __future__ import annotations

from db import BaseAsyncRepository
import db.models.ews as ews_models
from platform_core.db.types import DBAsyncScopedSession, DBAsyncSession

from ._crm_account_address_repo import CrmAccountAddressRepository
from ._crm_account_repo import CrmAccountRepository


type SessionLike = DBAsyncSession | DBAsyncScopedSession


ALL_REPOSITORIES = {
    'crm_account': CrmAccountRepository,
    'crm_account_address': CrmAccountAddressRepository,
}

MODEL_TO_REPOSITORY = {
    ews_models.CrmAccount: CrmAccountRepository,
    ews_models.CrmAccountAddress: CrmAccountAddressRepository,
}


class RepoFactory:
    """Factory for CRM repository classes and instances."""

    @staticmethod
    def get_repo(
        repository_type: type[BaseAsyncRepository],
        session: SessionLike,
    ) -> BaseAsyncRepository:
        return repository_type(session=session)

    @staticmethod
    def get_repo_by_name(name: str, session: SessionLike) -> BaseAsyncRepository:
        repository_type = ALL_REPOSITORIES.get(name)
        if repository_type is None:
            raise KeyError(f'No repository found for name: {name}')
        return repository_type(session=session)

    @staticmethod
    def get_repo_by_model(model_type: type, session: SessionLike) -> BaseAsyncRepository:
        repository_type = MODEL_TO_REPOSITORY.get(model_type)
        if repository_type is None:
            raise KeyError(f'No repository found for model: {model_type}')
        return repository_type(session=session)


__all__ = [
    'SessionLike',
    'RepoFactory',
    'ALL_REPOSITORIES',
    'MODEL_TO_REPOSITORY',
    'CrmAccountRepository',
    'CrmAccountAddressRepository',
]
