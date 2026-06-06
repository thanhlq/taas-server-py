from __future__ import annotations

from typing import Annotated
from uuid import UUID

from advanced_alchemy.service import OffsetPagination
from fastapi import Depends
from platform_core.db.advanced_session_manager import get_db_async_generator
from platform_core.exceptions.report_error import report_error
from platform_core.http import BaseController, delete, get, patch, post, status
from sqlalchemy.ext.asyncio import AsyncSession

from iam.accounts.schemas._user import User, UserCreate, UserUpdate
from iam.accounts.services._users import UserService


async def provide_users_service(
    db_session: Annotated[AsyncSession, Depends(get_db_async_generator)],
) -> UserService:
    """Provide a ``UserService`` bound to a request-scoped session."""
    return UserService(session=db_session)


UsersServiceDep = Annotated[UserService, Depends(provide_users_service)]


class UserController(BaseController):
    """User Account Controller."""

    api_prefix = '/api/v1/users'
    tags = ('Users',)
    count = 0

    @get('/')
    async def list_users(
        self, users_service: UsersServiceDep
    ) -> OffsetPagination[User]:
        """List all users."""
        results, total = await users_service.list_and_count()
        return users_service.to_schema(results, total, schema_type=User)

    @get('/{user_id}')
    async def get_user(self, user_id: UUID, users_service: UsersServiceDep) -> User:
        """Get a user by ID."""
        db_obj = await users_service.get(user_id)
        return users_service.to_schema(db_obj, schema_type=User)

    @post('/', status_code=status.HTTP_201_CREATED)
    async def create_user(
        self, data: UserCreate, users_service: UsersServiceDep
    ) -> User:
        data.properties = {
            "mfa_enabled": True,
            "backup_codes": 'asdfasf',
            "mfa_method": 'google',
            "mfa_secret": 'aasdfasf',
            "mfa_recovery_codes": ['code1', 'code2', 'code3'],
        }

        self.count += 1

        try:

            db_obj = await users_service.create(data=data.as_dict())
            return users_service.to_schema(db_obj, schema_type=User)
        except Exception as e:
            report_error(e)

    @patch('/{user_id}')
    async def update_user(
        self,
        user_id: UUID,
        data: UserUpdate,
        users_service: UsersServiceDep,
    ) -> User:
        """Update an existing user."""
        db_obj = await users_service.update(item_id=user_id, data=data.as_dict())
        return users_service.to_schema(db_obj, schema_type=User)

    @delete('/{user_id}', status_code=status.HTTP_204_NO_CONTENT)
    async def delete_user(self, user_id: UUID, users_service: UsersServiceDep) -> None:
        """Delete a user by ID."""
        await users_service.delete(user_id)
