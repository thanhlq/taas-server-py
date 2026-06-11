from __future__ import annotations

import asyncio

import db.models.core as m
from advanced_alchemy.extensions.fastapi import repository, service
from iam.constants import Roles
from platform_core.models import ListResult
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_scoped_session
from sqlalchemy.sql import text


class UserService(service.SQLAlchemyAsyncRepositoryService[m.User]):
    """Handles database operations for users."""

    class Repo(repository.SQLAlchemyAsyncRepository[m.User]):
        """User SQLAlchemy Repository."""

        model_type = m.User

    repository_type = Repo
    default_role = Roles.USER
    match_fields = ['email']

    async def do_list_users(self, session: AsyncSession | async_scoped_session[AsyncSession], limit: int = 100, offset: int = 0) -> list[m.User]:
        _session: AsyncSession
        if isinstance(session, async_scoped_session):
            _session = session()
        else:
            _session = session

        query = select(self.repository.model_type).order_by(m.User.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await _session.scalars(query)
        result = result.unique().all()

        return result

    # @db_concurrent_session
    async def list_users_fast(self, session: async_scoped_session[AsyncSession] | None = None, limit: int = 100, offset: int = 0) -> ListResult[m.User]:
        async with asyncio.TaskGroup() as tg:
            t_select = tg.create_task(self.do_list_users(session, limit, offset))
            t_count = tg.create_task(self.count_fast(session))

        return ListResult(
            data=t_select.result(),
            total_count=t_count.result(),
        )


    async def count_fast(self, session: AsyncSession | async_scoped_session[AsyncSession]) -> int:
        """
        Fastest count by using this sql:
        SELECT reltuples::bigint FROM pg_class WHERE relname = 'taas_user_account';
        """
        _session: AsyncSession
        if isinstance(session, async_scoped_session):
            _session = session()
        else:
            _session = session

        sql = f'SELECT reltuples::bigint FROM pg_class WHERE relname = \'{self.repository.model_type.__tablename__}\';'
        query = text(sql)
        result = await _session.scalar(query)
        return int(result)
