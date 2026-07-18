from __future__ import annotations

from uuid import UUID

# from fastapi import Depends
from foundation.db.advanced_db_manager import (
    MainDatabase,
    db_concurrent_session,
    db_context_session,
)
from foundation.db.types import DBAsyncScopedSession, DBAsyncSession
from foundation.http import BaseController, cache, delete, get, patch, post, status

# async def provide_users_service(
#     db_session: Annotated[AsyncSession, Depends(get_db_async_generator)],
# ) -> UserService:
#     """Provide a ``UserService`` bound to a request-scoped session."""
#     return UserService(session=db_session)


# UsersServiceDep = Annotated[UserService, Depends(provide_users_service)]


def get_auth_service(session) -> UserService:
    return AuthService(session=session or MainDatabase.get_instance().new_session())


class AuthController(BaseController):
    """Authentication Controller."""

    api_prefix = '/api/v1/auth'
    tags = ('Authentication',)

    @get('/signup-info')
    @db_concurrent_session
    @cache(expire=60)  # Cache the response for 60 seconds
    async def get_signup_info(self, session: DBAsyncScopedSession) -> dict:
        return {
            'signup_enabled': True,
            'email_verification_required': True,
            'password_policy': {
                'min_length': 8,
                'require_uppercase': True,
                'require_lowercase': True,
                'require_numbers': True,
                'require_special_characters': True,
            },
            'required_fields': ['email', 'password', 'first_name', 'last_name'],
            'organization_policy': {
                'required_fields': ['name'],
                'require_domain_verification': False,
            },
        }

    @get('/{user_id}')
    @db_concurrent_session
    async def get_user(self, user_id: UUID, session: DBAsyncScopedSession) -> User:
        """Get a user by ID."""
        users_service = AccountFactory.get_user_service(session)
        db_obj = await users_service.get(user_id)
        return users_service.to_schema(db_obj, schema_type=User)

    # ratelimit='5000/minute' does not work
    @post('/', status_code=status.HTTP_201_CREATED)
    @db_context_session(auto_commit=True)
    async def create_user(self, data: UserCreate, session: DBAsyncSession) -> User:

        users_service = AccountFactory.get_user_service(session)

        data.properties = {
            'mfa_enabled': True,
            'backup_codes': 'asdfasf',
            'mfa_method': 'google',
            'mfa_secret': 'aasdfasf',
            'mfa_recovery_codes': ['code1', 'code2', 'code3'],
        }

        db_obj = await users_service.create(data=data.as_dict())
        return users_service.to_schema(db_obj, schema_type=User)

    @patch('/{user_id}')
    @db_context_session
    async def update_user(
        self,
        user_id: UUID,
        data: UserUpdate,
        session: DBAsyncSession,
    ) -> User:
        """Update an existing user."""
        users_service = AccountFactory.get_user_service(session)
        db_obj = await users_service.update(item_id=user_id, data=data.as_dict())
        return users_service.to_schema(db_obj, schema_type=User)

    @delete('/{user_id}', status_code=status.HTTP_204_NO_CONTENT)
    @db_context_session
    async def delete_user(self, user_id: UUID, session: DBAsyncSession) -> None:
        """Delete a user by ID."""
        users_service = AccountFactory.get_user_service(session)
        await users_service.delete(user_id)
