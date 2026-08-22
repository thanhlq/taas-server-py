from db.models import User
from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncSession
from iam.common.base import BaseIamService
from iam.iam_constants import IamEvents, get_iam_topic_for_event

from ..helpers.users_helper import IamDataHelper


class UsersService(BaseIamService):
    """Users service for managing IAM resources."""

    def __init__(self):
        super().__init__()

    async def search_users(
        self,
        search_text: str, **kwargs
    ) -> User:
        return await self._search_users(search_text, **kwargs)

    @db_context_session()
    async def _search_users(
        self,
        search_text: str,
        session: DBAsyncSession,
        **kwargs
    ) -> User:
        """Create a new user in the system."""

        #
        # 1. Create user & tenant
        #

        user_repo = self.get_user_repository(session)

        _user, _tenant = IamDataHelper.build_root_account(
            directory_user, directory_tenant
        )

        # Create the tenant first
        new_tenant = await tenant_repo.add(_tenant)

        # Create the user and associate it with the newly created tenant
        new_user = await user_repo.add(_user)

        #
        # 2. Publish the UserRegisteredEvent to its mapped topic
        #
        # Route via get_iam_topic_for_event, the same resolver that drives Avro
        # schema registration. These two publishes previously targeted iam.auth,
        # which carries no schema for either event — so under Avro they failed
        # outright, and under a schema-less codec they landed on a topic no
        # consumer of these events subscribes to.
        _e_user_registered = IamDataHelper.build_user_registered_event(
            new_user, new_tenant, directory_user, directory_tenant
        )

        await self.message_routing_service.publish_event(
            _e_user_registered,
            channel=get_iam_topic_for_event(IamEvents.USER_REGISTERED),
            session=session,
        )

        #
        # 3. Publish the TenantCreatedEvent to its mapped topic
        #

        _e_tenant_created = IamDataHelper.build_tenant_created_event(
            new_user, new_tenant, directory_user, directory_tenant
        )

        await self.message_routing_service.publish_event(
            _e_tenant_created,
            channel=get_iam_topic_for_event(IamEvents.TENANT_CREATED),
            session=session,
        )

        return new_user
