"""RFC 9068 JWT access tokens + OIDC id_token builder."""

from __future__ import annotations

import time
import uuid
from typing import Any, Optional

from authlib.jose import jwt

from iam_oauth.config import OAuthServerConfig
from iam_oauth.jwks import JWKSManager
from iam_oauth.models.entities import User


class TokenBuilder:
    def __init__(self, *, config: OAuthServerConfig, jwks: JWKSManager):
        self._cfg = config
        self._jwks = jwks

    # ----- RFC 9068 JWT access token ----------------------------------------
    def access_token(self, *, user: User, client_id: str, scope: str) -> str:
        now = int(time.time())
        header = {'alg': self._cfg.signing_alg, 'typ': 'at+jwt',
                  'kid': self._jwks.signing_key.tokens.get('kid')}
        payload = {
            'iss': self._cfg.issuer,
            'sub': user.id,
            'aud': client_id,
            'client_id': client_id,
            'iat': now,
            'nbf': now,
            'exp': now + self._cfg.access_token_ttl,
            'jti': uuid.uuid4().hex,
            'scope': scope,
        }
        return jwt.encode(header, payload, self._jwks.signing_key).decode()

    # ----- OIDC id_token config (consumed by OpenIDCode) --------------------
    def jwt_config(self) -> dict[str, Any]:
        return {
            'key': self._jwks.signing_key,
            'alg': self._cfg.signing_alg,
            'iss': self._cfg.issuer,
            'exp': self._cfg.id_token_ttl,
        }

    def userinfo_claims(self, user: User, scope: str) -> dict[str, Any]:
        scopes = set(scope.split())
        claims: dict[str, Any] = {'sub': user.id}
        if 'email' in scopes:
            claims['email'] = user.email
            claims['email_verified'] = user.email_verified
        return claims
