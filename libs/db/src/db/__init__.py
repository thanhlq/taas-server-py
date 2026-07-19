from sqlalchemy.ext.asyncio import AsyncEngine

from .models.base import AdvancedDeclarativeBase
from .common.base_repo import AsyncSession, BaseAsyncRepository, BaseModelT
from .common.exceptions import ConflictError, NotFoundError, RepositoryError
from .utils.utils import DBUtils


async def create_db_and_run_migrations(engine: AsyncEngine) -> None:
    """
    Create the database if it doesn't exist, then run all pending migrations.

    """
    async with engine.begin() as connection:
        await connection.run_sync(AdvancedDeclarativeBase.metadata.create_all)


__all__ = [
    'DBUtils',
    'create_db_and_run_migrations',
    'BaseAsyncRepository',
    'BaseModelT',
    'AsyncSession',
    'ConflictError',
    'NotFoundError',
    'RepositoryError',
]
