from __future__ import annotations

import asyncio

import db.models.core as m
from advanced_alchemy.extensions.fastapi import repository, service
from iam.constants import Roles
from foundation.db.types import DBAsyncScopedSession, DBAsyncSession
from foundation.models import ListResult
from sqlalchemy.ext.asyncio import AsyncSession, async_scoped_session
from sqlalchemy.sql import text
from iam.schemas import Role


class RoleService(service.SQLAlchemyAsyncRepositoryService[m.Role]):
    """Handles database operations for roles."""

    class Repo(repository.SQLAlchemyAsyncRepository[m.Role]):
        """Role SQLAlchemy Repository."""

        model_type = m.Role

    repository_type = Repo
    default_role = Roles.USER
    match_fields = ['email']

    def get_session(self) -> DBAsyncSession:
        """Get the current database session."""
        return self.repository.session

    def to_db_role(self, role_create: Role) -> m.Role:
        return m.Role(
            name=role_create.name,
            description=role_create.description,
        )

    async def create_role(self, role: Role, **kwargs) -> m.Role:
        """Create a new role with the default role."""
        role_row = self.to_db_role(role, **kwargs)
        return await self.create(role_row)


    async def list_roles_fast(self, limit: int = 100, offset: int = 0) -> ListResult[m.Role]:
        session: DBAsyncScopedSession = self.get_session()
        async with asyncio.TaskGroup() as tg:
            t_select = tg.create_task(self.do_list_roles(session, limit, offset))
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
        _session: AsyncSession = self.get_session()
        # if isinstance(session, async_scoped_session):
        #     _session = session()
        # else:
        #     _session = session

        sql = f'SELECT reltuples::bigint FROM pg_class WHERE relname = \'{self.repository.model_type.__tablename__}\';'
        query = text(sql)
        result = await _session.scalar(query)
        return int(result)


class UserRole(service.SQLAlchemyAsyncRepositoryService[m.Role]):
    """Handles database operations for roles."""

    class Repo(repository.SQLAlchemyAsyncRepository[m.Role]):
        """Role SQLAlchemy Repository."""

        model_type = m.Role

    repository_type = Repo
    default_role = Roles.USER
    match_fields = ['email']

    def get_session(self) -> DBAsyncSession:
        """Get the current database session."""
        return self.repository.session

    def to_db_role(self, role_create: Role) -> m.Role:
        return m.Role(
            name=role_create.name,
            description=role_create.description,
        )

    async def create_role(self, role: Role, **kwargs) -> m.Role:
        """Create a new role with the default role."""
        role_row = self.to_db_role(role, **kwargs)
        return await self.create(role_row)


    async def list_roles_fast(self, limit: int = 100, offset: int = 0) -> ListResult[m.Role]:
        session: DBAsyncScopedSession = self.get_session()
        async with asyncio.TaskGroup() as tg:
            t_select = tg.create_task(self.do_list_roles(session, limit, offset))
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
        _session: AsyncSession = self.get_session()
        # if isinstance(session, async_scoped_session):
        #     _session = session()
        # else:
        #     _session = session

        sql = f'SELECT reltuples::bigint FROM pg_class WHERE relname = \'{self.repository.model_type.__tablename__}\';'
        query = text(sql)
        result = await _session.scalar(query)
        return int(result)
