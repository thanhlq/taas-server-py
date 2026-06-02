from enum import StrEnum


class Roles(StrEnum):
    """Predefined user roles."""

    TENANT_ADMIN = 'tenant_admin'  # Has access to all resources within a tenant
    ORGANIZATION_ADMIN = 'organization_admin'  # In a specific organization
    USER = 'user'  # Regular user in a tenant with limited access
