from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import db.models.core as m
from advanced_alchemy.extensions.fastapi import service
from ews.core import CoreRepositoryFactory
from foundation.db.types import DBAsyncSession
from foundation.models import ListResult
from iam.accounts.schemas._user import UserCreate, UserStatus
from iam.iam_constants import Roles
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_scoped_session
from sqlalchemy.sql import text

if TYPE_CHECKING:
    from iam.accounts.services._role import RoleService

class UserService(service.SQLAlchemyAsyncRepositoryService[m.User]):
    """Handles database operations for users."""


    repository_type = CoreRepositoryFactory.user_repo()
    default_role = Roles.USER
    match_fields = ['email']

    def get_session(self) -> DBAsyncSession:
        """Get the current database session."""
        s = self.repository.session
        if isinstance(s, async_scoped_session):
            # print('⏰. async_scoped_session session')
            return s()
        return s

    def role_service(self) -> 'RoleService':
        from iam.accounts.services._role import RoleService

        return RoleService(session=self.get_session())

    async def create_user(self, user: UserCreate, **kwargs) -> m.User:
        """Create a new user with the default role."""
        user_row = self.user_create_to_db_user(user)
        return await self.create(user_row, **kwargs)

    async def addRoleToUser(self, user_id: int, role_name: str | None, role_id: str | None, org_id: int) -> m.UserRole:
        if role_name is None and role_id is None:
            raise ValueError("Either role_name or role_id must be provided.")

        if role_id is None:
            role_id = await self.role_service().get_role_id_by_name(role_name)

        db_row = m.UserRole(
            user_id=user_id,
            role_id=role_id,
            org_id=org_id
        )
        rs = self.role_service()
        role = await rs.create(db_row)
        return role


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
