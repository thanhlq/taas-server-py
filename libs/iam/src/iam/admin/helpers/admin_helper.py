from db.models import User
from db.models.core import Tenant
from foundation.iam.types import UserStatus
from foundation.utils.id import generate_tenant_id
from iam.auth.auth_events import (
    TenantCreatedEvent,
    UserDirectoryEventPayload,
    UserRegisteredEvent,
)
from iam.auth.types import DirectoryTenant, DirectoryUser


class IamDataHelper:
    """Helper for building IAM data models from directory (or other sources) data."""

    @staticmethod
    def build_root_account(
        directory_user: DirectoryUser, directory_tenant: DirectoryTenant
    ) -> tuple[User, Tenant]:

        # Build tenant
        tenant: Tenant = Tenant()
        tenant.name = directory_tenant.name
        tenant.description = directory_tenant.description
        tenant.alias_id = directory_tenant.alias_id
        tenant.directory_id = directory_tenant.id
        # tenant.realm_name = event.realm_name
        tenant.id = generate_tenant_id()

        # Build user
        user: User = User()
        user.username = directory_user.username
        user.email = directory_user.email
        user.first_name = directory_user.first_name
        user.last_name = directory_user.last_name
        user.status = (
            UserStatus.ACTIVE if directory_user.enabled else UserStatus.INACTIVE
        )
        user.tenant_id = tenant.id
        tenant.root_account_id = user.id

        return (user, tenant)

    @staticmethod
    def build_user_registered_event(
        user: User,
        tenant: Tenant,
        directory_user: DirectoryUser,
        directory_tenant: DirectoryTenant,
    ) -> UserRegisteredEvent:
        """Build the payload for a UserRegisteredEvent from directory data."""

        _payload = UserDirectoryEventPayload(
            user=directory_user,
            tenant=directory_tenant,
        )

        u_registered_event: UserRegisteredEvent = UserRegisteredEvent(
            user_id=str(user.id),
            email=user.email,
            username=user.username,
            tenant_id=str(tenant.id),
        )
        u_registered_event.set_payload_object(_payload)

        return u_registered_event

    @staticmethod
    def build_tenant_created_event(
        user: User,
        tenant: Tenant,
        directory_user: DirectoryUser,
        directory_tenant: DirectoryTenant,
    ) -> TenantCreatedEvent:
        """Build the payload for a TenantCreatedEvent from directory data."""

        _payload = UserDirectoryEventPayload(
            user=directory_user,
            tenant=directory_tenant,
        )

        t_created_event = TenantCreatedEvent(
            tenant_id=str(tenant.id),
            root_account_id=str(user.id),
            # payload=created_tenant.as_dict(),
            # root_account=created_user.as_dict(),
        )

        t_created_event.set_payload_object(_payload)

        return t_created_event
