"""
Global types for IAM module.

The rules:
    - All types must be serializable to JSON, database columns, and Python objects.
    - For the serious data types should be StrEnum i.e. SubscriptionPackage, UserRequiredActions, etc.
    - For the simple data types should be IntEnum i.e. UserType, UserCategory for best performance and storage.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum, StrEnum, IntEnum
from typing import Optional, TypedDict

from foundation.serialization import BaseModel, BaseEntity


class TeamType(IntEnum):
    """Type of team."""

    GENERAL = 1
    DEPARTMENT = 2
    PROJECT = 3

class TeamStatus(IntEnum):
    """Team lifecycle status."""

    ACTIVE = 1
    INACTIVE = 2
    SUSPENDED = 3
    CLOSED = 4

class TenantStatus(IntEnum):
    """Tenant lifecycle status."""

    ACTIVE = 1
    INACTIVE = 2
    SUSPENDED = 3
    CLOSED = 4
    DELETED = 5


class OrganizationStatus(IntEnum):
    """Organization lifecycle status."""

    ACTIVE = 1
    INACTIVE = 2
    SUSPENDED = 3
    CLOSED = 4

class OrganizationType(IntEnum):
    """Type of organization"""

    COMPANY = 1
    NON_PROFIT = 2
    GOVERNMENT = 3
    EDUCATIONAL = 4
    PERSONAL = 5


class Phone(TypedDict):
    number: str
    is_verified: bool
    verified_at: datetime | None
    type: str | None
    """ 'mobile', 'home', 'work' """
    is_primary: bool
    country_code: str  # e.g., '+1', '+44'


class UserStatus(IntEnum):
    ACTIVE = 1
    INACTIVE = 2
    SUSPENDED = 3
    DELETED = 4
    BLOCKED = 5


class TeamRoles(StrEnum):
    """Valid Values for Team Roles."""

    ADMIN = 'ADMIN'
    MEMBER = 'MEMBER'


class OrganizationRoles(StrEnum):
    """Valid Values for Organization Roles."""

    ADMIN = 'ADMIN'
    MEMBER = 'MEMBER'


class AuthUser(BaseModel):
    """
    Represents an authenticated user.
    """

    id: str
    name: str | None = None
    username: str | None = None
    # family_name: str  # last_name
    # given_name: str  # first_name
    last_name: str = ''
    first_name: str = ''
    # preferred_username: str
    sub: str = ''
    email_verified: bool = False
    roles: list[str] = []


class TaxNumber(BaseModel):
    country_code: str
    tax_number: str
    primary: Optional[bool] = False


class WithdrawConfirmationMethod(Enum):
    OTP = 'otp'
    EMAIL = 'email'


class UserType(IntEnum):
    PERSONAL = 1
    BUSINESS = 2
    TEST = 3
    SYSTEM = 4


class UserCategory(IntEnum):
    CLIENT_USERS = 1
    COLLABORATORS = 2
    INTERNAL_USERS = 3


class UserProfileKycStatus(StrEnum):
    COMPLETED = 'completed'
    PARTIAL = 'partial'
    BANNED = 'banned'


class UserSubscriptionPackage(StrEnum):
    FREE = 'free'
    PRO = 'pro'
    BUSINESS = 'business'
    ENTERPRISE = 'enterprise'
    CUSTOM = 'custom'


class UserRequiredActions(StrEnum):
    UPDATE_USER_LOCALE = 'UPDATE_USER_LOCALE'
    TERMS_AND_CONDITIONS = 'TERMS_AND_CONDITIONS'
    CONFIGURE_TOTP = 'CONFIGURE_TOTP'
    VERIFY_EMAIL = 'VERIFY_EMAIL'
    UPDATE_PASSWORD = 'UPDATE_PASSWORD'
    UPDATE_PROFILE = 'UPDATE_PROFILE'





class Organization(BaseEntity):
    """Contain exactly needed database fields for organization."""

    id: str
    name: str
    slug: str
    status: OrganizationStatus
