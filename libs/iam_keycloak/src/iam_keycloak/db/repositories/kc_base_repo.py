from __future__ import annotations

from typing import Dict, Generic, List, Optional, Union

from core.db.engine import DBAsyncSession
from core.db.sa.repository_base import BaseRepository, DomainModelT, OrmModelT
from core.db.types import (
    db_not_deleted,
)

from ..kc_db import kc_db_session_async as db_session_async


class KeycloakBaseRepository(
    BaseRepository[OrmModelT, DomainModelT], Generic[OrmModelT, DomainModelT]
):
    """
    Base repository which use the specific KEYCLOAK decorator (for the keycloak database)
    """

    @db_session_async
    async def upsert(
        self,
        id: str,
        model: Union[DomainModelT, dict],
        session: DBAsyncSession,
        **kwargs,
    ) -> DomainModelT:
        return await self.upsert_with_session(id, model, session, **kwargs)

    @db_session_async
    async def add(
        self, model: Union[DomainModelT, dict], session: DBAsyncSession, *args, **kwargs
    ) -> Union[DomainModelT, str]:
        return await self.add_with_session(model, session, *args, **kwargs)

    @db_session_async
    async def exists(self, session: DBAsyncSession, **kwargs) -> bool:
        return await self.db_exists(session, **kwargs)

    @db_session_async
    async def delete(self, uuid: str, session: DBAsyncSession, *args, **kwargs):
        return await self.delete_with_session(uuid, session, *args, **kwargs)

    @db_session_async
    async def delete_permanently_by_id(
        self, uuid: str, session: DBAsyncSession, **kwargs
    ) -> int:
        return await self.db_delete_permanently_by_id(uuid, session, **kwargs)

    @db_session_async
    async def delete_permanently(self, session: DBAsyncSession, **kwargs) -> int:
        return await self.delete_permanently_with_session(session, **kwargs)

    @db_session_async
    async def get(self, id, session: DBAsyncSession, **kwargs) -> Optional[OrmModelT]:
        return await self.get_with_session(id, session, **kwargs)

    @db_session_async
    async def get_by_user(
        self, user_uuid: str, session: DBAsyncSession, **kwargs
    ) -> list[DomainModelT] | DomainModelT:
        return await self.get_by_user_with_session(user_uuid, session, **kwargs)

    @db_session_async
    @db_not_deleted
    async def first(self, session: DBAsyncSession, **kwargs) -> Optional[OrmModelT]:
        return await self.db_first(session, **kwargs)

    @db_session_async
    @db_not_deleted
    async def last(self, session: DBAsyncSession, **kwargs) -> Optional[DomainModelT]:
        return await self.last_with_session(session, **kwargs)

    @db_session_async
    async def update(
        self,
        uuid: str,
        model: Union[DomainModelT, dict],
        session: DBAsyncSession,
        *args,
        **kwargs,
    ) -> DomainModelT:
        return await self.update_with_session(uuid, model, session, *args, **kwargs)

    @db_session_async
    async def batch_update(
        self, models: Dict[str, DomainModelT], session: DBAsyncSession, *args, **kwargs
    ) -> List[DomainModelT]:
        return await self.batch_update_with_session(models, session, *args, **kwargs)

    @db_session_async
    async def batch_add(
        self, models: list[DomainModelT], session: DBAsyncSession, **kwargs
    ) -> list[str]:
        return await self.batch_add_with_session(models, session, **kwargs)

    @db_session_async
    @db_not_deleted
    async def count(self, session: DBAsyncSession, **kwargs) -> int:
        return await self.count_with_session(session, **kwargs)

    @db_session_async
    @db_not_deleted
    async def sum(self, key: str, session: DBAsyncSession, **kwargs) -> float:
        return await self.sum_with_session(key, session, **kwargs)

    @db_session_async
    @db_not_deleted
    async def list(self, session: DBAsyncSession, **kwargs) -> list[DomainModelT]:
        return await self.list_with_session(session, **kwargs)
