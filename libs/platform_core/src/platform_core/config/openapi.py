"""OpenAPI / Swagger-UI configuration for Litestar apps.

Mirrors the Swagger-UI + OAuth2/PKCE setup configured for FastAPI in
:mod:`http_fastapi.base_fastapi_app`, so the docs experience is consistent
regardless of which framework ``ews_api`` is wired to.

Litestar exposes the schema endpoints under a single ``path`` prefix
(default ``/schema``). We point it at ``/docs`` and default the landing page
to Swagger-UI so ``GET /docs`` renders the interactive docs like FastAPI; the
raw document is then served at ``/docs/openapi.json``.
"""
from __future__ import annotations

from typing import Any

from platform_core.openapi.config import OpenAPIConfig

DEFAULT_TITLE = 'eWorkSuite API'
DEFAULT_VERSION = '1.0.0'

# OAuth2 redirect endpoint used by Swagger-UI (kept in sync with http_fastapi).
SWAGGER_OAUTH2_REDIRECT_URL = 'https://api.eworksuite.com/docs/oauth2-redirect'

# Passed to Swagger-UI's ``initOAuth``. ``usePkceWithAuthorizationCodeGrant``
# enables PKCE for the Authorization Code flow.
SWAGGER_INIT_OAUTH: dict[str, Any] = {
    'clientId': 'eworksuite-web',
    # 'clientSecret': settings.KEYCLOAK_LOGIN_CLIENT_SECRET,  # only for confidential clients
    'appName': 'eWorkSuite API Documentation',
    'scopes': 'openid profile email',
    'usePkceWithAuthorizationCodeGrant': True,
}

def build_openapi_config(
    *,
    title: str = DEFAULT_TITLE,
    version: str = DEFAULT_VERSION,
    **kwargs: Any,
) -> OpenAPIConfig:
    """Build an :class:`OpenAPIConfig` mirroring the FastAPI docs setup."""
    kwargs.setdefault('path', '/docs')
    kwargs.setdefault('root_schema_site', 'swagger')
    return OpenAPIConfig(title=title, version=version, **kwargs)
