"""Storage protocols.

The OAuth server depends only on these protocols; a concrete SQLAlchemy
implementation lives in :mod:`iam_oauth.models`. Tests can substitute
in-memory fakes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Protocol, runtime_checkable

from iam_oauth.models.entities import (
    AuthorizationCode,
    Client,
    FederatedIdentity,
    MagicLinkToken,
    PasskeyCredential,
    RefreshToken,
    User,
)


@runtime_checkable
class ClientRepository(Protocol):
    async def get(self, client_id: str) -> Optional[Client]: ...


@runtime_checkable
class UserRepository(Protocol):
    async def get(self, user_id: str) -> Optional[User]: ...
    async def get_by_email(self, email: str) -> Optional[User]: ...
    async def create(self, *, email: str, password_hash: Optional[str] = None) -> User: ...
    async def update_password(self, user_id: str, password_hash: str) -> None: ...


@runtime_checkable
class AuthorizationCodeRepository(Protocol):
    async def save(self, code: AuthorizationCode) -> None: ...
    async def pop(self, code: str) -> Optional[AuthorizationCode]: ...


@runtime_checkable
class RefreshTokenRepository(Protocol):
    async def save(self, token: RefreshToken) -> None: ...
    async def get(self, refresh_token: str) -> Optional[RefreshToken]: ...
    async def revoke(self, refresh_token: str) -> None: ...


@runtime_checkable
class MagicLinkRepository(Protocol):
    async def save(self, token: MagicLinkToken) -> None: ...
    async def pop(self, token_id: str) -> Optional[MagicLinkToken]: ...


@runtime_checkable
class PasskeyRepository(Protocol):
    async def list_for_user(self, user_id: str) -> list[PasskeyCredential]: ...
    async def get(self, credential_id: bytes) -> Optional[PasskeyCredential]: ...
    async def save(self, cred: PasskeyCredential) -> None: ...
    async def update_sign_count(self, credential_id: bytes, sign_count: int, last_used_at: datetime) -> None: ...


@runtime_checkable
class FederatedIdentityRepository(Protocol):
    async def get(self, provider: str, subject: str) -> Optional[FederatedIdentity]: ...
    async def link(self, *, user_id: str, provider: str, subject: str, email: Optional[str]) -> FederatedIdentity: ...
