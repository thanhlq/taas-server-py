"""Domain entities used by repositories and grants.

These are framework-agnostic dataclasses. A concrete SQLAlchemy mapping can
live alongside (see ``iam_oauth.models.sqlalchemy`` — not scaffolded here).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass(slots=True)
class User:
    id: str
    email: str
    password_hash: Optional[str] = None       # None ⇒ passwordless-only
    email_verified: bool = False
    disabled: bool = False
    created_at: Optional[datetime] = None


@dataclass(slots=True)
class Client:
    client_id: str
    client_secret: Optional[str]              # None for public clients (SPA, mobile)
    redirect_uris: list[str]
    grant_types: list[str]
    response_types: list[str]
    scope: str
    token_endpoint_auth_method: str = 'client_secret_basic'
    require_pkce: bool = True


@dataclass(slots=True)
class AuthorizationCode:
    code: str
    client_id: str
    user_id: str
    redirect_uri: str
    scope: str
    code_challenge: Optional[str]
    code_challenge_method: Optional[str]
    nonce: Optional[str]
    auth_time: int
    expires_at: datetime


@dataclass(slots=True)
class RefreshToken:
    token: str
    client_id: str
    user_id: str
    scope: str
    expires_at: datetime
    revoked: bool = False


@dataclass(slots=True)
class MagicLinkToken:
    id: str                                    # opaque id embedded in the link
    email: str
    expires_at: datetime
    consumed: bool = False
    next_url: Optional[str] = None             # original /authorize URL to resume


@dataclass(slots=True)
class PasskeyCredential:
    credential_id: bytes
    user_id: str
    public_key: bytes
    sign_count: int
    transports: list[str] = field(default_factory=list)
    aaguid: Optional[bytes] = None
    created_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None


@dataclass(slots=True)
class FederatedIdentity:
    provider: str                              # 'google' | 'microsoft' | 'apple'
    subject: str                               # the upstream `sub` claim
    user_id: str
    email: Optional[str] = None
