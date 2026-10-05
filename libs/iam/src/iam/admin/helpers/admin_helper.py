from db.models import User
from db.models.core import CasbinRule, Organization, OrganizationMember, Tenant
from foundation.iam.types import (
    MembershipJoinedVia,
    OrganizationRoles,
    TenantAccountType,
    TenantStatus,
    UserStatus,
    rbac_domain,
)
from foundation.utils.id import generate_otp, generate_tenant_id_str, generate_uuid
from foundation.utils.str_utils import slugify
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
        tenant.id = generate_uuid()
        tenant.tenant_code = generate_tenant_id_str()
        tenant.name = directory_tenant.name
        tenant.description = directory_tenant.description
        tenant.alias_id = directory_tenant.alias_id
        tenant.directory_id = directory_tenant.id
        # Unique: the directory alias when there is one, else the name plus a short suffix.
        tenant.slug = directory_tenant.alias_id or f'{slugify(value=directory_tenant.name)}-{generate_otp(6)}'
        tenant.is_root = directory_tenant.is_root_tenant
        tenant.account_type = TenantAccountType.ORGANIZATION.value
        # Iam-0400: organization accounts complete the onboarding at first login.
        tenant.status = TenantStatus.ONBOARDING
        tenant.sys_settings = {}

        # Build user
        user: User = User()
        # Assign the id up-front (UUIDv7) so it can be referenced before flush,
        # e.g. as the tenant's root_account_id below. The DB-side default would
        # otherwise only populate user.id at INSERT time, leaving it None here.
        user.id = generate_uuid()
        user.directory_id = directory_user.id
        user.username = directory_user.username
        user.email = directory_user.email.lower()
        user.first_name = directory_user.first_name
        user.last_name = directory_user.last_name
        user.status = (
            UserStatus.ACTIVE if directory_user.enabled else UserStatus.INACTIVE
        )
        user.name = f'{directory_user.first_name} {directory_user.last_name}'.strip()
        user.email_verified = directory_user.email_verified
        user.is_root_account = True
        user.tenant_id = tenant.id
        tenant.root_account_id = user.id

        return (user, tenant)

    @staticmethod
    def build_root_organization(
        user: User, tenant: Tenant
    ) -> tuple[Organization, OrganizationMember, CasbinRule]:
        """Root organization of the tenant (Iam-0120), its owner membership and the
        Tenant Admin grant (``g, <user>, tenant_admin, tenant:<tenant>``)."""
        org_id = generate_uuid()
        organization = Organization(
            id=org_id,
            tenant_id=tenant.id,
            parent_id=None,
            path=f'/{org_id}/',
            depth=0,
            name=tenant.name,
            slug=f'{tenant.slug}-root',
            directory_id=tenant.directory_id,
        )
        member = OrganizationMember(
            id=generate_uuid(),
            tenant_id=tenant.id,
            user_id=user.id,
            organization_id=org_id,
            role=OrganizationRoles.TENANT_ADMIN.value,
            is_owner=True,
            joined_via=MembershipJoinedVia.REGISTRATION.value,
        )
        grant = CasbinRule(
            ptype='g',
            v0=str(user.id),
            v1=OrganizationRoles.TENANT_ADMIN.value,
            v2=rbac_domain('tenant', tenant.id),
        )
        return organization, member, grant

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
