"""Authorization Code + PKCE grant (Authlib).

This is the *only* interactive grant we support. Password / magic-link /
passkey / federation are all just different ways of authenticating the
**user** before the ``/authorize`` endpoint returns a code.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from authlib.oauth2.rfc6749 import grants
from authlib.oidc.core import grants as oidc_grants

from iam_oauth.models.entities import AuthorizationCode, User
from iam_oauth.repositories import (
    AuthorizationCodeRepository,
    ClientRepository,
    UserRepository,
)


class AuthorizationCodePKCEGrant(grants.AuthorizationCodeGrant):
    """Auth Code + PKCE — PKCE is mandatory for both public and confidential clients."""

    TOKEN_ENDPOINT_AUTH_METHODS = [
        'client_secret_basic',
        'client_secret_post',
        'none',  # public clients (SPA/mobile) — PKCE compensates
    ]

    def __init__(
        self,
        *args,
        code_repo: AuthorizationCodeRepository,
        user_repo: UserRepository,
        code_ttl: int = 60,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._code_repo = code_repo
        self._user_repo = user_repo
        self._code_ttl = code_ttl

    async def save_authorization_code(self, code: str, request) -> None:  # type: ignore[override]
        ac = AuthorizationCode(
            code=code,
            client_id=request.client.client_id,
            user_id=str(request.user.id),
            redirect_uri=request.redirect_uri,
            scope=request.scope,
            code_challenge=request.data.get('code_challenge'),
            code_challenge_method=request.data.get('code_challenge_method'),
            nonce=request.data.get('nonce'),
            auth_time=int(datetime.now(tz=timezone.utc).timestamp()),
            expires_at=datetime.now(tz=timezone.utc) + timedelta(seconds=self._code_ttl),
        )
        await self._code_repo.save(ac)

    async def query_authorization_code(self, code: str, client) -> Optional[AuthorizationCode]:  # type: ignore[override]
        ac = await self._code_repo.pop(code)
        if ac is None or ac.client_id != client.client_id:
            return None
        if ac.expires_at < datetime.now(tz=timezone.utc):
            return None
        return ac

    async def delete_authorization_code(self, authorization_code) -> None:  # type: ignore[override]
        # ``pop`` already removed it in ``query_authorization_code``.
        return

    async def authenticate_user(self, authorization_code) -> Optional[User]:  # type: ignore[override]
        return await self._user_repo.get(authorization_code.user_id)


class OpenIDCode(oidc_grants.OpenIDCode):
    """Mixin that augments Authorization Code with ``id_token`` issuance."""

    def __init__(self, *, require_nonce: bool = True, id_token_builder):
        super().__init__(require_nonce=require_nonce)
        self._id_token_builder = id_token_builder

    def exists_nonce(self, nonce: str, request) -> bool:
        # Stateless: the nonce is echoed into id_token; replays are bounded by
        # the auth-code single-use semantics.
        return False

    def get_jwt_config(self, grant):
        return self._id_token_builder.jwt_config()

    def generate_user_info(self, user, scope):
        return self._id_token_builder.userinfo_claims(user, scope)


def new_random_token(n_bytes: int = 32) -> str:
    return secrets.token_urlsafe(n_bytes)
