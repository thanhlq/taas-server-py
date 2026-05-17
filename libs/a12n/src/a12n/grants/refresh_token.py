"""Refresh-token grant (Authlib)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from authlib.oauth2.rfc6749 import grants

from iam_oauth.models.entities import RefreshToken, User
from iam_oauth.repositories import RefreshTokenRepository, UserRepository


class RefreshTokenGrant(grants.RefreshTokenGrant):
    TOKEN_ENDPOINT_AUTH_METHODS = ['client_secret_basic', 'client_secret_post', 'none']
    INCLUDE_NEW_REFRESH_TOKEN = True

    def __init__(
        self,
        *args,
        refresh_repo: RefreshTokenRepository,
        user_repo: UserRepository,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._refresh_repo = refresh_repo
        self._user_repo = user_repo

    async def authenticate_refresh_token(self, refresh_token: str) -> Optional[RefreshToken]:  # type: ignore[override]
        rt = await self._refresh_repo.get(refresh_token)
        if rt is None or rt.revoked:
            return None
        if rt.expires_at < datetime.now(tz=timezone.utc):
            return None
        return rt

    async def authenticate_user(self, credential) -> Optional[User]:  # type: ignore[override]
        return await self._user_repo.get(credential.user_id)

    async def revoke_old_credential(self, credential) -> None:  # type: ignore[override]
        await self._refresh_repo.revoke(credential.token)
