from __future__ import annotations

import db.models.banking as m
import msgspec
from advanced_alchemy import repository, service

from ..schemas import CryptoToken as CryptoTokenCreate

# Columns of the ORM model we can populate from the create payload.
_TOKEN_COLUMNS = {column.name for column in m.CryptoToken.__table__.columns}


def new_token_to_db_token(token: CryptoTokenCreate) -> m.CryptoToken:
    """Map a create payload to an ORM row.

    Copies every field shared by the schema and the model, skipping ``None`` so
    database/server defaults still apply (e.g. ``categories``, ``is_stable_coin``).
    """
    data = msgspec.structs.asdict(token)
    kwargs = {
        key: value
        for key, value in data.items()
        if key in _TOKEN_COLUMNS and value is not None
    }
    return m.CryptoToken(**kwargs)


class CryptoTokenService(service.SQLAlchemyAsyncRepositoryService[m.CryptoToken]):
    """Handles database operations for crypto tokens."""

    class Repo(repository.SQLAlchemyAsyncRepository[m.CryptoToken]):
        """CryptoToken SQLAlchemy Repository."""

        model_type = m.CryptoToken

    repository_type = Repo

    async def create_crypto_token(self, token: CryptoTokenCreate) -> m.CryptoToken:
        row = new_token_to_db_token(token)

        return await self.create(row)
