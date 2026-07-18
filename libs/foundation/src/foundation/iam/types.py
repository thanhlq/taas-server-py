"""Global types for IAM module."""

from __future__ import annotations

from datetime import datetime
from enum import Enum, StrEnum
from typing import Optional, TypedDict

from foundation.serialization import BaseModel


class Phone(TypedDict):
    number: str
    is_verified: bool
    verified_at: datetime | None
    type: str | None
    """ 'mobile', 'home', 'work' """
    is_primary: bool
    country_code: str  # e.g., '+1', '+44'


class UserStatus(StrEnum):
    ACTIVE = 'active'
    INACTIVE = 'inactive'
    SUSPENDED = 'suspended'
    DELETED = 'deleted'
    BLOCKED = 'blocked'


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


class UserType(Enum):
    PERSONAL = 'Personal'
    BUSINESS = 'Business'
    TEST = 'Test'
    SYSTEM = 'System'


class UserCategory(Enum):
    CLIENT_USERS = 'client'
    COLLABORATORS = 'collab'
    INTERNAL_USERS = 'internal'


class UserProfileKycStatus(Enum):
    COMPLETED = 'completed'
    PARTIAL = 'partial'
    BANNED = 'banned'


class UserSubscriptionPackage(Enum):
    FREE = 'free'
    PRO = 'pro'
    BUSINESS = 'business'
    ENTERPRIRSE = 'enterprise'
    CUSTOM = 'custom'


class UserRequiredActions(Enum):
    UPDATE_USER_LOCALE = 'UPDATE_USER_LOCALE'
    TERMS_AND_CONDITIONS = 'TERMS_AND_CONDITIONS'
    CONFIGURE_TOTP = 'CONFIGURE_TOTP'
    VERIFY_EMAIL = 'VERIFY_EMAIL'
    UPDATE_PASSWORD = 'UPDATE_PASSWORD'
    UPDATE_PROFILE = 'UPDATE_PROFILE'
