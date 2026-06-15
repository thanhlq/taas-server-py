from __future__ import annotations

import db.models.banking as m
from advanced_alchemy.extensions.fastapi import repository, service

from ..schemas import CryptoToken as CryptoTokenCreate


def new_token_to_db_token(token: CryptoTokenCreate) -> m.CryptoToken:
    return m.CryptoToken(
        name=token.name,
        symbol=token.symbol,
        decimals=token.decimals,
        blockchain=token.blockchain,
        network=token.network,
        type=token.type,
        contract_address=token.contract_address,
    )


class CryptoTokenService(service.SQLAlchemyAsyncRepositoryService[m.CryptoToken]):
    """Handles database operations for crypto tokens."""

    class Repo(repository.SQLAlchemyAsyncRepository[m.CryptoToken]):
        """CryptoToken SQLAlchemy Repository."""

        model_type = m.CryptoToken

    repository_type = Repo

    async def create_crypto_token(self, token: CryptoTokenCreate) -> m.CryptoToken:
        row = new_token_to_db_token(token)

        return await self.create(row)
