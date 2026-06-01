from enum import StrEnum


class TenantStatus(StrEnum):
    """Tenant lifecycle status."""

    ACTIVE = 'active'
    INACTIVE = 'inactive'
    SUSPENDED = 'suspended'
    CLOSED = 'closed'

class OrganizationStatus(StrEnum):
    """Organization lifecycle status."""

    ACTIVE = 'active'
    INACTIVE = 'inactive'
    SUSPENDED = 'suspended'
    CLOSED = 'closed'

class OrganizationType(StrEnum):
    """Type of organization"""

    COMPANY = 'company'
    NON_PROFIT = 'non_profit'
    GOVERNMENT = 'government'
    EDUCATIONAL = 'educational'
    PERSONAL = 'personal'
