from typing import Any, Sequence, TypeVar

from advanced_alchemy.base import ModelProtocol
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ModelT = TypeVar('ModelT', bound=ModelProtocol)


async def select_by_sql[ModelT](
    raw_sql: str,
    params: dict[str, Any],
    session: AsyncSession,
    domain_model: type[ModelT] | None = None,
) -> Sequence[dict]:
    """Execute a raw SQL query and return results as domain models or dictionaries."""
    # To be compatible with PonyORM / when all queries updated, could remove this line
    raw_sql = raw_sql.replace('$', ':')

    db_resp = await session.execute(text(raw_sql), params)
    results = db_resp.all()

    print(f"select_by_sql: {raw_sql} with params: {params} returned {len(results)} rows, type: {type(results[0]) if len(results) > 0 else 'N/A'}")

    return [row._asdict() for row in results]
