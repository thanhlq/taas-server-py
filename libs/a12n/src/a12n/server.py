"""High-level façade that wires Authlib's ``AuthorizationServer`` together.

Construction is dependency-injected so the same server can be exercised in
tests with in-memory fakes.
"""

from __future__ import annotations

from typing import Optional

from authlib.integrations.starlette_oauth2 import AuthorizationServer
from authlib.oauth2.rfc7009 import RevocationEndpoint
from authlib.oauth2.rfc7662 import IntrospectionEndpoint

from iam_oauth.auth_methods import (
    MagicLinkAuthenticator,
    PasskeyAuthenticator,
    PasswordAuthenticator,
)
from iam_oauth.config import FederationConfig, OAuthServerConfig
from iam_oauth.federation import FederationRegistry
from iam_oauth.grants import (
    AuthorizationCodePKCEGrant,
    ClientCredentialsGrant,
    OpenIDCode,
    RefreshTokenGrant,
)
from iam_oauth.jwks import JWKSManager
from iam_oauth.repositories import (
    AuthorizationCodeRepository,
    ClientRepository,
    FederatedIdentityRepository,
    MagicLinkRepository,
    PasskeyRepository,
    RefreshTokenRepository,
    UserRepository,
)
from iam_oauth.tokens import TokenBuilder


class OAuthServer:
    """Composition root for the IdP."""

    def __init__(
        self,
        *,
        config: OAuthServerConfig,
        federation: FederationConfig,
        client_repo: ClientRepository,
        user_repo: UserRepository,
        code_repo: AuthorizationCodeRepository,
        refresh_repo: RefreshTokenRepository,
        magic_link_repo: MagicLinkRepository,
        passkey_repo: PasskeyRepository,
        federated_repo: FederatedIdentityRepository,
        password_auth: PasswordAuthenticator,
        magic_link_auth: MagicLinkAuthenticator,
        passkey_auth: PasskeyAuthenticator,
    ):
        self.config = config
        self.client_repo = client_repo
        self.user_repo = user_repo
        self.code_repo = code_repo
        self.refresh_repo = refresh_repo
        self.magic_link_repo = magic_link_repo
        self.passkey_repo = passkey_repo
        self.federated_repo = federated_repo
        self.password_auth = password_auth
        self.magic_link_auth = magic_link_auth
        self.passkey_auth = passkey_auth

        self.jwks = JWKSManager(private_jwks_path=config.jwks_private_keys_path)
        self.token_builder = TokenBuilder(config=config, jwks=self.jwks)
        self.federation = FederationRegistry(config=federation)

        self._server = AuthorizationServer(
            query_client=self._query_client,
            save_token=self._save_token,
        )
        self._register_grants()
        self._register_endpoints()

    # ---------------------------------------------------------------- public
    @property
    def server(self) -> AuthorizationServer:
        return self._server

    def discovery_document(self) -> dict:
        base = self.config.issuer.rstrip('/')
        return {
            'issuer': self.config.issuer,
            'authorization_endpoint': f'{base}/authorize',
            'token_endpoint': f'{base}/token',
            'userinfo_endpoint': f'{base}/userinfo',
            'jwks_uri': f'{base}/.well-known/jwks.json',
            'introspection_endpoint': f'{base}/introspect',
            'revocation_endpoint': f'{base}/revoke',
            'response_types_supported': ['code'],
            'grant_types_supported': ['authorization_code', 'refresh_token', 'client_credentials'],
            'scopes_supported': ['openid', 'email', 'profile', 'offline_access'],
            'token_endpoint_auth_methods_supported': [
                'client_secret_basic', 'client_secret_post', 'none',
            ],
            'code_challenge_methods_supported': ['S256'],
            'subject_types_supported': ['public'],
            'id_token_signing_alg_values_supported': [self.config.signing_alg],
        }

    # ---------------------------------------------------------------- wiring
    async def _query_client(self, client_id: str):
        return await self.client_repo.get(client_id)

    async def _save_token(self, token: dict, request) -> None:
        from datetime import datetime, timedelta, timezone

        from iam_oauth.models.entities import RefreshToken

        rt = token.get('refresh_token')
        if not rt or request.user is None:
            return
        await self.refresh_repo.save(RefreshToken(
            token=rt,
            client_id=request.client.client_id,
            user_id=str(request.user.id),
            scope=token.get('scope', ''),
            expires_at=datetime.now(tz=timezone.utc) + timedelta(seconds=self.config.refresh_token_ttl),
        ))

    def _register_grants(self) -> None:
        self._server.register_grant(
            AuthorizationCodePKCEGrant,
            [OpenIDCode(require_nonce=True, id_token_builder=self.token_builder)],
            grant_kwargs={
                'code_repo': self.code_repo,
                'user_repo': self.user_repo,
                'code_ttl': self.config.auth_code_ttl,
            },
        )
        self._server.register_grant(
            RefreshTokenGrant,
            grant_kwargs={'refresh_repo': self.refresh_repo, 'user_repo': self.user_repo},
        )
        self._server.register_grant(ClientCredentialsGrant)

    def _register_endpoints(self) -> None:
        self._server.register_endpoint(IntrospectionEndpoint)
        self._server.register_endpoint(RevocationEndpoint)
