from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from foundation.http.response import ApiResponse
from foundation.serialization._msgspec_model import BaseEventPayload

from iam.auth.schemas import SignupRequest
from iam.auth.schemas._auth import SignupRequestOut

if TYPE_CHECKING:
    # Imported for type-checking only to break the circular import with
    # ``iam.auth.auth_events`` (which imports DirectoryUser/DirectoryTenant from here).
    from iam.auth.auth_events import UserRegisteredEvent


class DirectoryUser(BaseEventPayload):
    """Represents a user in the identity directory (e.g. Keycloak, Zitadel)."""

    id: str
    email: str
    username: str
    first_name: str | None = None
    last_name: str | None = None
    email_verified: bool = False
    enabled: bool = True
    tenant_id: str | None = None
    is_root_account: bool = False
    """
    When True?
        - when the user is registered as the root account of a tenant:
        - I.e. not being created by an admin of an existing tenant, but rather as the first user of a new tenant.
    When False?
        - When the user is registered as a normal user of an existing tenant.
        - When joining the tenant via an invitation,
        - or being created by an admin of the tenant.
    """


class DirectoryTenant(BaseEventPayload):
    """Represents a tenant in the identity directory (e.g. Keycloak's Organization, Zitadel)."""

    id: str
    name: str
    alias_id: str | None = None
    """
    alias_id:
        - Unique human-readable identifier.
        - Used for domain names, URLs, and other user-facing identifiers.
        - Can be generated from the name, or provided by the user.
    """
    description: str | None = None
    enabled: bool = True
    is_root_tenant: bool = False
    """ The tenant own the platform, and can manage other tenants. """


class IamDirectoryServiceT(ABC):

    # REQ-AUTH-001: User Registration
    @abstractmethod
    async def create_directory_user(
        self, registration_data: SignupRequest, **kwargs
    ) -> SignupRequestOut:
        """
        REQ-AUTH-001: User Registration

        - 2.1.1.1: Email/password registration
        - 2.1.1.2: Social registration (Google, Microsoft)
        - 2.1.1.3: Email verification workflow (optional)
        - 2.1.1.4: User profile creation with custom attributes

        Register a new user, this user is normally inactive until email verified.
        The user will be assigned to a new tenant.
        """
        pass

    @abstractmethod
    async def signup_send_email_verification(
        self, user: "UserRegisteredEvent", **kwargs
    ): ...

    @abstractmethod
    async def signup_send_welcome_email(
        self, user: "UserRegisteredEvent", **kwargs
    ): ...

    @abstractmethod
    async def signup_send_otp_to_email(
        self,
        email: str,
        otp: str | None = None,
        title: str | None = None,
        description: str | None = None,
    ):...

class AuthResponse(ApiResponse):
    access_token: str
    expires_in: int
    refresh_token: str
    refresh_expires_in: int
    token_type: str
    id_token: Optional[str] = None
    not_before_policy: Optional[int] = None
    session_state: Optional[str] = None
    keep_signed_in: Optional[bool] = False

@dataclass
class SessionInfo:
    """User session information"""

    session_id: str
    user_id: str
    username: str | None
    # is_active: bool
    created_at: datetime | None = None
    last_activity: datetime | None = None
    expires_at: Optional[datetime] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    transient_user: Optional[bool] = False
    clients: dict[str, Any] | None = None
