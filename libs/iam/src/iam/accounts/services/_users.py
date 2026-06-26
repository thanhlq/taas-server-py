from __future__ import annotations

import asyncio

import db.models.core as m
from advanced_alchemy.extensions.fastapi import repository, service
from iam.accounts.schemas._user import UserCreate, UserStatus
from iam.constants import Roles
from platform_core.db.types import DBAsyncScopedSession, DBAsyncSession
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

    def get_session(self) -> DBAsyncSession:
        """Get the current database session."""
        s = self.repository.session
        if isinstance(s, async_scoped_session):
            # print('⏰. async_scoped_session session')
            return s()
        return s

    async def create_user(self, user: UserCreate, **kwargs) -> m.User:
        """Create a new user with the default role."""
        user_row = self.user_create_to_db_user(user)
        return await self.create(user_row, **kwargs)

    async def list_users_fast(
        self, limit: int = 100, offset: int = 0
    ) -> ListResult[m.User]:
        async with asyncio.TaskGroup() as tg:
            t_select = tg.create_task(self.do_list_users(limit, offset))
            t_count = tg.create_task(self.count_fast())

        return ListResult(
            data=t_select.result(),
            total_count=t_count.result(),
        )

    async def do_list_users(self, limit: int = 100, offset: int = 0) -> list[m.User]:
        _session = self.get_session()

        query = select(self.repository.model_type).order_by(m.User.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await _session.scalars(query)
        result = result.unique().all()

        return result

    async def count_fast(self) -> int:
        """
        Fastest count by using this sql:
        SELECT reltuples::bigint FROM pg_class WHERE relname = 'taas_user_account';
        """
        _session: AsyncSession = self.get_session()
        sql = f"SELECT reltuples::bigint FROM pg_class WHERE relname = '{self.repository.model_type.__tablename__}';"
        query = text(sql)
        result = await _session.scalar(query)
        return int(result)

    def user_create_to_db_user(self, user_create: UserCreate) -> m.User:
        """Convert UserCreate schema to User DB model."""
        user = m.User(
            email=user_create.email,
            name=user_create.name,
            role=self.default_role,
            tenant_id=user_create.tenant_id,
            org_id=user_create.org_id,
            status=user_create.status or UserStatus.ACTIVE,
            first_name=user_create.first_name,
            last_name=user_create.last_name,
            username=user_create.username,
            properties=user_create.properties,
            phones=user_create.phones,
        )

        return user
