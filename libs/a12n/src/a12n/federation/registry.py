"""Upstream OIDC federation (Google / Microsoft / Apple) via Authlib client."""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Optional

from authlib.integrations.starlette_client import OAuth, StarletteOAuth2App
from authlib.jose import jwt

from iam_oauth.config import FederationConfig, UpstreamProviderConfig


class FederationRegistry:
    """Wraps Authlib's ``OAuth`` registry; registers Google/Microsoft/Apple."""

    def __init__(self, *, config: FederationConfig):
        self._cfg = config
        self._oauth = OAuth()
        for provider in config.enabled():
            self._register(provider)

    @property
    def oauth(self) -> OAuth:
        return self._oauth

    def get(self, name: str) -> StarletteOAuth2App:
        client = self._oauth.create_client(name)
        if client is None:
            raise KeyError(f'Federation provider {name!r} is not configured')
        return client

    # ------------------------------------------------------------------------
    def _register(self, p: UpstreamProviderConfig) -> None:
        kwargs: dict = {
            'name': p.name,
            'client_id': p.client_id,
            'server_metadata_url': p.server_metadata_url,
            'client_kwargs': {'scope': ' '.join(p.scopes)},
        }
        if p.name == 'apple':
            # Apple requires client_assertion (JWT signed with the team's ES256 key)
            kwargs['client_secret'] = self._build_apple_client_secret(p)
            kwargs['client_kwargs']['token_endpoint_auth_method'] = 'client_secret_post'
        else:
            kwargs['client_secret'] = p.client_secret
        self._oauth.register(**kwargs)

    @staticmethod
    def _build_apple_client_secret(p: UpstreamProviderConfig) -> str:
        if not (p.apple_team_id and p.apple_key_id and p.apple_private_key_path):
            raise ValueError('Apple provider requires team_id, key_id and private_key_path')
        private_key = Path(p.apple_private_key_path).read_text()
        now = int(time.time())
        header = {'alg': 'ES256', 'kid': p.apple_key_id}
        payload = {
            'iss': p.apple_team_id,
            'iat': now,
            'exp': now + 60 * 60 * 24 * 180,  # max 6 months
            'aud': 'https://appleid.apple.com',
            'sub': p.client_id,
            'jti': uuid.uuid4().hex,
        }
        return jwt.encode(header, payload, private_key).decode()
