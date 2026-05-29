from sqlalchemy.ext.asyncio import AsyncEngine
from .models import AdvancedDeclarativeBase


async def create_db_and_run_migrations(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(AdvancedDeclarativeBase.metadata.create_all)
