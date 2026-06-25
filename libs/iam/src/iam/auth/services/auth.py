from __future__ import annotations
from iam.auth.schemas import SignupRequest

import asyncio

import db.models.core as m
from advanced_alchemy.extensions.fastapi import repository, service
from iam.accounts.schemas._user import UserCreate, UserStatus
from iam.constants import Roles
from platform_core.db.types import DBAsyncScopedSession
from platform_core.models import ListResult
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_scoped_session
from sqlalchemy.sql import text


class AuthService(service.SQLAlchemyAsyncRepositoryService[m.User]):
    class Repo(repository.SQLAlchemyAsyncRepository[m.User]):
        model_type = m.User

    repository_type = Repo
    default_role = Roles.USER
    match_fields = ['email']

    async def create_user(self, user: SignupRequest):
        """Create a new user with the default role."""
        user_row = self.user_create_to_db_user(user)
        return await self.create(user_row)
