"""Global types for IAM module."""

from datetime import datetime
from enum import StrEnum
from typing import TypedDict


class Phone(TypedDict):
    number: str
    is_verified: bool
    verified_at: datetime | None
    type: str | None
    is_primary: bool


class UserStatus(StrEnum):
    ACTIVE = 'active'
    INACTIVE = 'inactive'
    SUSPENDED = 'suspended'
    DELETED = 'deleted'
    BLOCKED = 'blocked'
