from db.models import User
from db.models.core import Tenant
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
        # One builder for root accounts (uuid tenant id, tenant_code, onboarding status).
        from iam.admin.helpers.admin_helper import IamDataHelper as AdminIamDataHelper

        return AdminIamDataHelper.build_root_account(directory_user, directory_tenant)

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
