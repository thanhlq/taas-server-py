"""Lightweight OAuth 2.1 / OIDC provider built on Authlib.

Public entry points:
    - :class:`iam_oauth.server.OAuthServer` — wraps Authlib's ``AuthorizationServer``.
    - :func:`iam_oauth.endpoints.build_router` — assembles the FastAPI router.
"""

from iam_oauth.server import OAuthServer

__all__ = ['OAuthServer']
