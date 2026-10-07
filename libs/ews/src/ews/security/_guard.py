"""Controller helpers: ``scope = await current_scope()`` then ``await authorize(scope, resource, action)``.

The scope is resolved once per request (cached on ``request.state``) from the request context
(``foundation.http.context_state``), so controllers stay framework-agnostic.
"""

from __future__ import annotations

from collections.abc import Sequence

from foundation.exceptions import NotAuthorizedException, PermissionDeniedException
from foundation.http.context_state import require_request_context

from ews.authz import can

from ._directory import DirectoryT, SqlDirectory
from ._scope import IamSessionVerifier, RequestScope, SessionVerifierT, resolve_scope
from ._settings import EwsAuthSettings, auth_settings

_directory: DirectoryT | None = None
_verifier: SessionVerifierT | None = None
_settings: EwsAuthSettings | None = None


def configure_security(
    *,
    directory: DirectoryT | None = None,
    verifier: SessionVerifierT | None = None,
    settings: EwsAuthSettings | None = None,
) -> None:
    """Replace the directory / session verifier / settings (tests); ``None`` restores the defaults."""
    global _directory, _verifier, _settings
    _directory, _verifier, _settings = directory, verifier, settings


def current_settings() -> EwsAuthSettings:
    return _settings or auth_settings()


def _deps() -> tuple[DirectoryT, SessionVerifierT | None]:
    global _directory, _verifier
    settings = current_settings()
    if _directory is None:
        _directory = SqlDirectory()
    if _verifier is None and settings.mode == 'iam':
        _verifier = IamSessionVerifier(settings.iam_url, settings.cache_seconds)
    return _directory, _verifier


async def current_scope() -> RequestScope:
    """The verified caller of the current request (401 signed out, 403 / 404 outside its tenants)."""
    try:
        ctx = require_request_context()
    except RuntimeError as error:
        raise NotAuthorizedException(detail='no request context') from error
    req = ctx.req
    cached = getattr(req.state, 'ews_scope', None)
    if isinstance(cached, RequestScope):
        return cached
    directory, verifier = _deps()
    headers = {k.lower(): v for k, v in req.headers.items()}
    scope = await resolve_scope(current_settings(), directory, verifier, headers, dict(req.cookies))
    req.state.ews_scope = scope
    return scope


async def is_allowed(scope: RequestScope, resource: str, action: str, domains: Sequence[str] | None = None) -> bool:
    """Permission check on ``domains`` (default: the organization chain + tenant). Development: allowed."""
    if scope.is_dev:
        return True
    return await can(scope.user_id, list(domains or scope.org_domains()), resource, action)


async def authorize(scope: RequestScope, resource: str, action: str, domains: Sequence[str] | None = None) -> None:
    """403 unless ``scope``'s user has ``resource:action`` on ``domains`` (most specific first)."""
    if not await is_allowed(scope, resource, action, domains):
        raise PermissionDeniedException(detail=f'missing permission {resource}:{action}')
