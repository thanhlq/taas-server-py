from __future__ import annotations

from typing import Any

from db import BaseAsyncRepository
import db.models.banking as banking_models
from platform_core.db.types import DBAsyncScopedSession, DBAsyncSession

from ._crypto_token_repo import CryptoTokenRepository

try:
    from ._crypto_transaction_representation_repo import (
        CryptoTransactionRepresentationRepository,
    )
except Exception:
    CryptoTransactionRepresentationRepository: (
        type[BaseAsyncRepository[Any]] | None
    ) = None


type SessionLike = DBAsyncSession | DBAsyncScopedSession


ALL_REPOSITORIES = {
    'crypto_token': CryptoTokenRepository,
}

if CryptoTransactionRepresentationRepository is not None:
    ALL_REPOSITORIES['crypto_transaction_representation'] = (
        CryptoTransactionRepresentationRepository
    )


MODEL_TO_REPOSITORY = {
    banking_models.CryptoToken: CryptoTokenRepository,
}

if CryptoTransactionRepresentationRepository is not None:
    from db.models.banking._crypto_tx_representation import (
        CryptoTransactionRepresentationOrm,
    )

    MODEL_TO_REPOSITORY[CryptoTransactionRepresentationOrm] = (
        CryptoTransactionRepresentationRepository
    )


class RepoFactory:
    """Factory for banking repository classes and instances."""

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
    'CryptoTokenRepository',
]

if CryptoTransactionRepresentationRepository is not None:
    __all__.append('CryptoTransactionRepresentationRepository')
