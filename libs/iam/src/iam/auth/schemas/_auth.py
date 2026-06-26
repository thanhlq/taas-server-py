"""User-related account schemas."""
from typing import Literal, TypedDict
from platform_core.serialization import BaseModel

from datetime import datetime
from uuid import UUID

import msgspec
from platform_core.iam.types import Phone, UserStatus
from platform_core.serialization._msgspec_model import ApiRequest
from platform_core.utils.validation import (
    validate_email,
    validate_name,
    validate_password,
    validate_phone,
    validate_username,
)


class SignupRequest(ApiRequest):
    """Holds team details for a user.

    This is nested in the User Model for 'team'
    """

    otp: str | None = None
    name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    organization: str | None = None
    mobile_phone: Phone | None = None
    password: str | None = None
    email: str | None = None

    @property
    def username(self) -> str | None:
        """Return the username based on the current settings."""
        from ..auth_settings import AuthSettings

        settings = AuthSettings()
        if settings.email_as_username:
            return self.email
        return None

    def __post_init__(self) -> None:
        from ..auth_settings import AuthSettings

        settings = AuthSettings()

        if settings.email_as_username:
            if not self.email:
                raise ValueError('Email is required.')

        if settings.saas_enabled and not self.organization:
            raise ValueError('Organization is required.')

        if self.name and not (self.first_name and self.last_name):
            # Try to split the name into first and last names if not provided
            name_parts = self.name.strip().split(' ', 1)
            self.first_name = name_parts[0]
            if len(name_parts) > 1:
                self.last_name = name_parts[1]


class DirectoryUser(TypedDict):
    pass

class DirectoryUserCreateResponse(BaseModel):
    id: str
    user: DirectoryUser
    status: Literal['OK', 'FAILED', 'EXISTED'] = 'OK'
    message: str | None = None
    verification_sent: bool = False
