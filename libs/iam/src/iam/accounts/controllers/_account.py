from __future__ import annotations

from uuid import UUID

import db.models.core as m
from advanced_alchemy.filters import LimitOffset, OrderBy
from advanced_alchemy.service import OffsetPagination

# from fastapi import Depends
from foundation.db.advanced_db_manager import (
    db_concurrent_session,
    db_context_session,
)
from foundation.db.types import DBAsyncScopedSession, DBAsyncSession
from foundation.http import BaseController, delete, get, patch, post, status
from foundation.http.context import Context
from foundation.models import ListResult
from sqlalchemy.ext.asyncio import AsyncSession, async_scoped_session

from iam.accounts.accounts_factory import UserAccountFactory
from iam.accounts.schemas._user import UserCreate, UserProfile, UserUpdate
from iam.accounts.services._users import UserService

# async def provide_users_service(
#     db_session: Annotated[AsyncSession, Depends(get_db_async_generator)],
# ) -> UserService:
#     """Provide a ``UserService`` bound to a request-scoped session."""
#     return UserService(session=db_session)


# UsersServiceDep = Annotated[UserService, Depends(provide_users_service)]


def get_user_service(session) -> UserService:

    return UserService(session=session)


class AccountController(BaseController):
    """User Account Controller."""

    api_prefix = '/api/v1/users'
    tags = ('User Account',)

    @get('/')
    @db_context_session
    async def list_users_slow(
        self,
        session: DBAsyncSession,
        ctx: Context,
    ) -> OffsetPagination[UserProfile]:
        """List all users."""

        # SLOW
        # order_filter = OrderBy(field_name="id", sort_order="asc")
        users_service = UserService(session=session)
        results, total = await users_service.get_many_and_count(
            LimitOffset(offset=0, limit=50), OrderBy(field_name='id', sort_order='asc')
        )

        return users_service.to_schema(results, total, schema_type=UserProfile)

    @get('/slow2')
    @db_concurrent_session
    async def list_users_slow2(
        self, session: async_scoped_session[AsyncSession]
    ) -> OffsetPagination[UserProfile]:
        """List all users."""

        users_service = UserAccountFactory.get_user_service(session)
        results, total = await users_service.get_many_and_count(
            LimitOffset(offset=0, limit=50), OrderBy(field_name='id', sort_order='asc')
        )

        return users_service.to_schema(results, total, schema_type=UserProfile)

        # return create_paginated_response[User](results, total=total)

    @get('/list_fast')
    @db_concurrent_session
    # @cache(expire=60)  # Cache the response for 60 seconds
    async def list_fast(self, session: DBAsyncScopedSession) -> OffsetPagination[UserProfile]:
        users_service = UserAccountFactory.get_user_service(session)
        results: ListResult[m.User] = await users_service.list_users_fast()
        return users_service.to_schema(
            results.data, results.total_count, schema_type=UserProfile
        )

    @get('/{user_id}')
    @db_concurrent_session
    async def get_user(self, user_id: UUID, session: DBAsyncScopedSession) -> UserProfile:
        """Get a user by ID."""
        users_service = UserAccountFactory.get_user_service(session)
        db_obj = await users_service.get(user_id)
        return users_service.to_schema(db_obj, schema_type=UserProfile)

    # ratelimit='5000/minute' does not work
    @post('/', status_code=status.HTTP_201_CREATED)
    @db_context_session(auto_commit=True)
    # @db_concurrent_session
    async def create_user(self, data: UserCreate, session: DBAsyncScopedSession) -> UserProfile:

        users_service = UserAccountFactory.get_user_service(session)

        data.properties = {
            'mfa_enabled': True,
            'backup_codes': 'asdfasf',
            'mfa_method': 'google',
            'mfa_secret': 'aasdfasf',
            'mfa_recovery_codes': ['code1', 'code2', 'code3'],
        }

        db_obj = await users_service.create(data=data.as_dict())
        return users_service.to_schema(db_obj, schema_type=UserProfile)

    @patch('/{user_id}')
    @db_context_session
    async def update_user(
        self,
        user_id: UUID,
        data: UserUpdate,
        session: DBAsyncSession,
    ) -> UserProfile:
        """Update an existing user."""
        users_service = UserAccountFactory.get_user_service(session)
        db_obj = await users_service.update(item_id=user_id, data=data.as_dict())
        return users_service.to_schema(db_obj, schema_type=UserProfile)

    @delete('/{user_id}', status_code=status.HTTP_204_NO_CONTENT)
    @db_context_session
    async def delete_user(self, user_id: UUID, session: DBAsyncSession) -> None:
        """Delete a user by ID."""
        users_service = UserAccountFactory.get_user_service(session)
        await users_service.delete(user_id)
