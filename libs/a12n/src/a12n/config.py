"""Runtime configuration for the OAuth/OIDC provider."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True, slots=True, kw_only=True)
class OAuthServerConfig:
    """Provider-wide configuration.

    Wire this up from your application settings layer; do not read env vars here.
    """

    # ---- Issuer / discovery -------------------------------------------------
    issuer: str
    """Public base URL of the IdP, e.g. ``https://auth.example.com``."""

    # ---- Token lifetimes (seconds) -----------------------------------------
    access_token_ttl: int = 900           # 15 min
    refresh_token_ttl: int = 60 * 60 * 24 * 30  # 30 days
    id_token_ttl: int = 900
    auth_code_ttl: int = 60
    magic_link_ttl: int = 60 * 10          # 10 min

    # ---- Signing keys -------------------------------------------------------
    jwks_private_keys_path: str = 'config/secrets/oauth_jwks_private.json'
    """Path to a JWKS document containing this IdP's private signing keys."""

    signing_alg: str = 'RS256'
    """JWS alg for id_token + JWT access tokens (RFC 9068)."""

    # ---- Session ------------------------------------------------------------
    session_cookie_name: str = 'iam_oauth_session'
    session_secret_path: str = 'config/secrets/oauth_session_secret'

    # ---- Password policy ----------------------------------------------------
    password_min_length: int = 10
    password_min_zxcvbn_score: int = 3   # 0..4

    # ---- WebAuthn / Passkey -------------------------------------------------
    webauthn_rp_id: str = 'example.com'
    webauthn_rp_name: str = 'EworkSuite'
    webauthn_origin: str = 'https://example.com'

    # ---- Federated providers (filled by FederationConfig children) ---------
    federation_enabled: bool = True

    # ---- Email --------------------------------------------------------------
    magic_link_from: str = 'no-reply@example.com'
    magic_link_subject: str = 'Sign in to EworkSuite'


@dataclass(frozen=True, slots=True, kw_only=True)
class UpstreamProviderConfig:
    """One entry per upstream OIDC IdP (Google, Microsoft, Apple, ...)."""

    name: str
    client_id: str
    server_metadata_url: str
    client_secret: Optional[str] = None      # Apple uses client_assertion instead
    apple_team_id: Optional[str] = None
    apple_key_id: Optional[str] = None
    apple_private_key_path: Optional[str] = None
    scopes: tuple[str, ...] = ('openid', 'email', 'profile')


@dataclass(frozen=True, slots=True, kw_only=True)
class FederationConfig:
    google: Optional[UpstreamProviderConfig] = None
    microsoft: Optional[UpstreamProviderConfig] = None
    apple: Optional[UpstreamProviderConfig] = None

    def enabled(self) -> list[UpstreamProviderConfig]:
        return [p for p in (self.google, self.microsoft, self.apple) if p is not None]
