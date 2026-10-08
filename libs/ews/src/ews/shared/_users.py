"""Display labels of users (``taas_user_account``) for lists: lock holders, revision authors, …"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def user_names(
    session: AsyncSession, ids: Iterable[UUID | None]
) -> dict[UUID, str]:
    """``{user id: name, else e-mail}`` of the known users among ``ids`` (unknown ids are left out)."""
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    rows = await session.execute(
        text(
            "select id, coalesce(nullif(name, ''), email) as label from taas_user_account where id = any(:ids)"
        ),
        {'ids': list(wanted)},
    )
    return {r.id: r.label for r in rows}
