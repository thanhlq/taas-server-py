from typing import Union

from advanced_alchemy.filters import StatementFilter
from db.models import User
from db.models.core import Tenant
from foundation.db.advanced_db_manager import MainDatabase, db_context_session
from foundation.db.types import DBAsyncSession
from iam.auth.types import DirectoryTenant, DirectoryUser
from iam.common.base import BaseIamService
from iam.iam_constants import IamTopics, TestMode
from sqlalchemy import ColumnElement

from ..helpers.admin_helper import IamDataHelper

FILTER_TYPE = Union[StatementFilter, ColumnElement[bool]]


class AdminService(BaseIamService):
    """Admin service for managing IAM resources."""

    def __init__(self):
        super().__init__()

    async def create_root_account_from_directory(
        self, user: DirectoryUser, tenant: DirectoryTenant, **kwargs
    ) -> User:
        return await self._create_root_account_from_directory(user, tenant, **kwargs)

    @db_context_session(auto_commit=True)
    async def _create_root_account_from_directory(
        self,
        directory_user: DirectoryUser,
        directory_tenant: DirectoryTenant,
        session: DBAsyncSession,
    ) -> User:
        """Create a new user in the system."""

        #
        # 1. Create user & tenant
        #

        user_repo = self.get_user_repository(session)
        tenant_repo = self.get_tenant_repository(session)

        # 01. Check if the user already exists in the system
        existing_user = await user_repo.get_one_or_none(
            email=directory_user.email, username=directory_user.username
        )
        if existing_user:
            if TestMode.SIGNUP_TEST_MODE:
                await self.delete_root_account(user=existing_user)
            else:
                raise ValueError(
                    f'User with email {directory_user.email} or username {directory_user.username} already exists.'
                )

        _user, _tenant = IamDataHelper.build_root_account(
            directory_user, directory_tenant
        )

        # self.logger.debug(f'Building root account from directory user and tenant {_user.id}')
        # self.logger.debug(f'user: {_user}')
        # self.logger.debug(f'tenant: {_tenant}')

        # Create the tenant first
        new_tenant = await tenant_repo.add(_tenant)

        # Create the user and associate it with the newly created tenant
        new_user = await user_repo.add(_user)

        #
        # 2. Publish the UserRegisteredEvent to the IAM_AUTH topic
        #

        _e_user_registered = IamDataHelper.build_user_registered_event(
            new_user, new_tenant, directory_user, directory_tenant
        )

        await self.message_routing_service.publish_event(
            _e_user_registered, channel=IamTopics.IAM_USER_REGISTER, session=session
        )

        #
        # 3. Publish the TenantCreatedEvent to the IAM_AUTH topic
        #

        _e_tenant_created = IamDataHelper.build_tenant_created_event(
            new_user, new_tenant, directory_user, directory_tenant
        )

        await self.message_routing_service.publish_event(
            _e_tenant_created, channel=IamTopics.IAM_USER_REGISTER, session=session
        )

        return new_user

    async def delete_root_account(
        self,
        *,
        user_email: str | None = None,
        user: User | None = None,
        session: DBAsyncSession | None = None,
    ) -> None:

        if not user_email and not user:
            raise ValueError('Either user_email or user must be provided.')

        self.logger.info(
            f'⚠️ Deleting root account for user_email: {user_email}, user: {str(user.id) if user else "N/A"}'
        )

        _session = session or MainDatabase.get_instance().get_current_or_new_session()

        """Delete a user and their associated tenant from the system."""
        user_repo = self.get_user_repository(_session)
        tenant_repo = self.get_tenant_repository(_session)

        # Fetch the user to get the associated tenant_id
        if user is None:
            user = await user_repo.get_one_or_none(email=user_email)
        if not user:
            raise ValueError(f'User with email {user_email} does not exist.')

        print(f'User to delete: {user.tenant_id}')
        tenant: Tenant = await tenant_repo.get(user.tenant_id)
        if not tenant:
            raise ValueError(f'Tenant with id {user.tenant_id} does not exist.')

        # Delete the user
        # await user_repo.delete(user.id)
        await _session.delete(user)
        await _session.delete(tenant)

        if session is None:
            # Commit when using a new session, but not when using an existing session (the caller will handle commit)
            await _session.commit()
