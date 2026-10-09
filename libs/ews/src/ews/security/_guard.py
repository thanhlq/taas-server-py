"""Controller helpers: ``scope = await current_scope()`` then ``await authorize(scope, resource, action)``.

The scope is resolved once per request (cached on ``request.state``) from the request context
(``foundation.http.context_state``), so controllers stay framework-agnostic.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import NAMESPACE_URL, UUID, uuid5

from foundation.exceptions import NotAuthorizedException, PermissionDeniedException
from foundation.http.context_state import require_request_context

from ews.authz import can

from ._csrf import allowed_web_origins, check_origin
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
    """The verified caller of the current request (401 signed out, 403 / 404 outside its tenants; 403 for a
    cookie-authenticated write from a foreign origin — CSRF, ``_csrf.py``)."""
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
    url = req.url
    check_origin(req.method, headers, f'{url.scheme}://{url.netloc}', allowed_web_origins())
    scope = await resolve_scope(current_settings(), directory, verifier, headers, dict(req.cookies))
    req.state.ews_scope = scope
    return scope


async def scope_of(user_ref: str, organization_id: UUID, user_id: UUID | None = None) -> RequestScope | None:
    """A scope acting as a user in an organization, outside a request (jobs and automation rules running as their
    owner): ``None`` when the organization is unknown or the user is not one of its members any more. Development
    sign-in: every permission, like a request."""
    directory, _ = _deps()
    organization = await directory.organization(organization_id)
    if organization is None:
        return None
    dev = current_settings().mode == 'dev'
    user = await directory.user_by_email(user_ref) if '@' in user_ref else None
    user_id = user.id if user else user_id
    if dev:
        # the development sign-in's id of an e-mail without a directory account
        user_id = user_id or uuid5(NAMESPACE_URL, f'taas-dev-user:{user_ref.lower()}')
    else:
        if user_id is None:
            return None
        members = await directory.memberships(user_id)
        if not any(organization.path.startswith(m.organization.path) for m in members):
            return None
    return RequestScope(
        user_id=user_id,
        email=user_ref if '@' in user_ref else None,
        name=None,
        tenant_id=organization.tenant_id,
        organization=organization,
        is_dev=dev,
    )


async def is_allowed(scope: RequestScope, resource: str, action: str, domains: Sequence[str] | None = None) -> bool:
    """Permission check on ``domains`` (default: the organization chain + tenant). Development: allowed."""
    if scope.is_dev:
        return True
    return await can(scope.user_id, list(domains or scope.org_domains()), resource, action)


async def authorize(scope: RequestScope, resource: str, action: str, domains: Sequence[str] | None = None) -> None:
    """403 unless ``scope``'s user has ``resource:action`` on ``domains`` (most specific first)."""
    if not await is_allowed(scope, resource, action, domains):
        raise PermissionDeniedException(detail=f'missing permission {resource}:{action}')
