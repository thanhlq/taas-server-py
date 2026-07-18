"""Authentication models"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Dict, List, Optional

from foundation.serialization import BaseModel


class AuthUser(BaseModel):
    """Represents an authenticated user."""

    id: str
    name: Optional[str] = None
    username: Optional[str] = None
    # family_name: str  # last_name
    # given_name: str  # first_name
    last_name: str = ''
    first_name: str = ''
    # preferred_username: str
    sub: str = ''
    email_verified: bool = False
    roles: List[str] = []





class AuthenticationResult(StrEnum):
    """Authentication result status"""

    SUCCESS = 'success'
    INVALID_CREDENTIALS = 'invalid_credentials'
    ACCOUNT_LOCKED = 'account_locked'
    ACCOUNT_DISABLED = 'account_disabled'
    PASSWORD_EXPIRED = 'password_expired'
    MFA_REQUIRED = 'mfa_required'
    EMAIL_VERIFICATION_REQUIRED = 'email_verification_required'
    CHALLENGE_REQUIRED = 'challenge_required'


class MfaMethod(StrEnum):
    """Multi-factor authentication methods"""

    SMS = 'sms'
    EMAIL = 'email'
    TOTP = 'totp'  # Time-based One-Time Password (Google Authenticator, etc.)
    WEBAUTHN = 'webauthn'  # WebAuthn/FIDO2
    PUSH_NOTIFICATION = 'push'
    BACKUP_CODES = 'backup_codes'


class SocialProvider(StrEnum):
    """Social login providers"""

    GOOGLE = 'google'
    FACEBOOK = 'facebook'
    MICROSOFT = 'microsoft'
    APPLE = 'apple'
    GITHUB = 'github'
    LINKEDIN = 'linkedin'
    TWITTER = 'twitter'


class TokenType(StrEnum):
    """Token types"""

    ACCESS_TOKEN = 'access_token'
    REFRESH_TOKEN = 'refresh_token'
    ID_TOKEN = 'id_token'
    SESSION_TOKEN = 'session_token'


@dataclass
class AuthContext:
    """Context information for authentication requests"""

    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    device_id: Optional[str] = None
    geolocation: Optional[Dict[str, Any]] = None
    request_id: Optional[str] = None
