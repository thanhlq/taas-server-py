"""Keycloak IAM settings.

User-defined settings (read from the environment) for the Keycloak identity
and access management integration. Follows the same pattern as
``foundation.config.email_settings.EmailSettings``: a plain ``dataclass`` whose
fields default to ``get_env(...)`` factories so every value can be overridden
via an environment variable of the same name.

Field names deliberately keep the ``KEYCLOAK_`` prefix so they match both the
keys in ``sample.env`` and the existing call sites (e.g.
``settings.KEYCLOAK_API``, ``settings.KEYCLOAK_LOGIN_CLIENT_ID``).

See :mod:`iam_keycloak` ``sample.env`` for the full list of keys.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

from foundation.utils.env_utils import get_env


@dataclass
class KeycloakSettings:
    """Keycloak identity and access management settings.

    All values are sourced from environment variables (same name as the field)
    and fall back to the defaults below when unset. Secrets (client/admin
    secrets, DB password) default to empty/``None`` and MUST be supplied via the
    environment in any real deployment.
    """

    # ── Core realm / server ────────────────────────────────────────────────
    KEYCLOAK_REALM: str = field(
        default_factory=get_env('KEYCLOAK_REALM', 'eworksuite')
    )
    """🏛️ Keycloak realm name."""

    KEYCLOAK_API: str = field(
        default_factory=get_env('KEYCLOAK_API', 'http://localhost:9090', str)
    )
    """🔗 Keycloak server API/base URL (e.g. ``https://kc.example.com``)."""

    # ── Clients ────────────────────────────────────────────────────────────
    KEYCLOAK_CLIENT_ID: str = field(
        default_factory=get_env('KEYCLOAK_CLIENT_ID', 'eworksuite-web', str)
    )
    """🎫 Default Keycloak client ID."""

    KEYCLOAK_LOGIN_CLIENT_ID: str = field(
        default_factory=get_env('KEYCLOAK_LOGIN_CLIENT_ID', 'eworksuite-web', str)
    )
    """🔑 Client ID used for the login/token exchange flow."""

    KEYCLOAK_LOGIN_CLIENT_SECRET: Optional[str] = field(
        default_factory=get_env('KEYCLOAK_LOGIN_CLIENT_SECRET', None, str)
    )
    """🔐 Login client secret (confidential client)."""

    KEYCLOAK_OTP_CLIENT_ID: Optional[str] = field(
        default_factory=get_env('KEYCLOAK_OTP_CLIENT_ID', None, str)
    )
    """📱 OTP (one-time password) client ID."""

    KEYCLOAK_OTP_CLIENT_SECRET: Optional[str] = field(
        default_factory=get_env('KEYCLOAK_OTP_CLIENT_SECRET', None, str)
    )
    """🔐 OTP client secret."""

    # ── Admin credentials ──────────────────────────────────────────────────
    KEYCLOAK_ADMIN_USER: Optional[str] = field(
        default_factory=get_env('KEYCLOAK_ADMIN_USER', None, str)
    )
    """👤 Keycloak admin username."""

    KEYCLOAK_ADMIN_SECRET: Optional[str] = field(
        default_factory=get_env('KEYCLOAK_ADMIN_SECRET', None, str)
    )
    """🔑 Keycloak admin password/secret."""

    # ── Flow / transport ───────────────────────────────────────────────────
    KEYCLOAK_REDIRECT_URL: Optional[str] = field(
        default_factory=get_env('KEYCLOAK_REDIRECT_URL', None, str)
    )
    """🔄 Redirect URL after authentication."""

    KEYCLOAK_SSL_VERIFY: bool = field(
        default_factory=get_env('KEYCLOAK_SSL_VERIFY', False)
    )
    """🔒 Verify Keycloak's TLS certificate (disable only for local/dev)."""

    # ── Keycloak database (may differ from the main application DB) ─────────
    # KEYCLOAK_POSTGRES_HOST: Optional[str] = field(
    #     default_factory=get_env('KEYCLOAK_POSTGRES_HOST', None, str)
    # )
    # """🖥️ Keycloak PostgreSQL host."""

    # KEYCLOAK_POSTGRES_PORT: int = field(
    #     default_factory=get_env('KEYCLOAK_POSTGRES_PORT', 5432, int)
    # )
    # """🔌 Keycloak PostgreSQL port."""

    # KEYCLOAK_POSTGRES_USER: Optional[str] = field(
    #     default_factory=get_env('KEYCLOAK_POSTGRES_USER', 'postgres', str)
    # )
    # """👤 Keycloak PostgreSQL username."""

    # KEYCLOAK_POSTGRES_PASSWORD: Optional[str] = field(
    #     default_factory=get_env('KEYCLOAK_POSTGRES_PASSWORD', '', str)
    # )
    # """🔑 Keycloak PostgreSQL password."""

    # KEYCLOAK_DB: Optional[str] = field(
    #     default_factory=get_env('KEYCLOAK_DB', 'keycloak', str)
    # )
    """🗄️ Keycloak database name."""

    # def keycloak_db_url(self) -> str:
    #     return f'postgresql+psycopg_async://{self.KEYCLOAK_POSTGRES_USER}:{self.KEYCLOAK_POSTGRES_PASSWORD}@{self.KEYCLOAK_POSTGRES_HOST}:{self.KEYCLOAK_POSTGRES_PORT}/{self.KEYCLOAK_DB}'

    def __post_init__(self):
        """Validate settings after initialization."""
        if not self.KEYCLOAK_API:
            raise ValueError(
                "Keycloak API URL [KEYCLOAK_API] is not set in the environment."
            )

        if not self.KEYCLOAK_REALM:
            raise ValueError(
                "Keycloak realm [KEYCLOAK_REALM] is not set in the environment."
            )

        if not self.KEYCLOAK_CLIENT_ID:
            raise ValueError(
                "Keycloak client ID [KEYCLOAK_CLIENT_ID] is not set in the environment."
            )

        if not self.KEYCLOAK_LOGIN_CLIENT_SECRET:
            raise ValueError(
                "Keycloak login client secret [KEYCLOAK_LOGIN_CLIENT_SECRET] is not set in the environment."
            )

        if not self.KEYCLOAK_ADMIN_USER:
            raise ValueError(
                "Keycloak admin username [KEYCLOAK_ADMIN_USER] is not set in the environment."
            )

        if not self.KEYCLOAK_ADMIN_SECRET:
            raise ValueError(
                "Keycloak admin secret [KEYCLOAK_ADMIN_SECRET] is not set in the environment."
            )

        # if not self.KEYCLOAK_POSTGRES_HOST:
        #     raise ValueError(
        #         "Keycloak PostgreSQL host [KEYCLOAK_POSTGRES_HOST] is not set in the environment."
        #     )
        # if not self.KEYCLOAK_POSTGRES_PORT:
        #     raise ValueError(
        #         "Keycloak PostgreSQL port [KEYCLOAK_POSTGRES_PORT] is not set in the environment."
        #     )
        # if not self.KEYCLOAK_POSTGRES_USER:
        #     raise ValueError(
        #         "Keycloak PostgreSQL user [KEYCLOAK_POSTGRES_USER] is not set in the environment."
        #     )
        # if not self.KEYCLOAK_POSTGRES_PASSWORD:
        #     raise ValueError(
        #         "Keycloak PostgreSQL password [KEYCLOAK_POSTGRES_PASSWORD] is not set in the environment."
        #     )
        # if not self.KEYCLOAK_DB:
        #     raise ValueError(
        #         "Keycloak database [KEYCLOAK_DB] is not set in the environment."
        #     )


@lru_cache(maxsize=1)
def get_keycloak_settings() -> KeycloakSettings:
    """Return process-wide Keycloak settings, read from the environment once."""
    return KeycloakSettings()
