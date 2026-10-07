"""Request authentication and authorization of the EWS business apps (sites, media, …).

``scope = await current_scope()`` → verified user + tenant + organization (``EWS_AUTH_MODE`` ``iam`` |
``dev``), ``await authorize(scope, 'sites.page', 'update', domains)`` → 403 unless granted.
Spec: taas-specs/iam/specs/authorization-rbac-spec.md §2, §5.
"""

from ._directory import (
    DirectoryMembership,
    DirectoryOrganization,
    DirectoryT,
    DirectoryUser,
    SqlDirectory,
)
from ._guard import authorize, configure_security, current_scope, current_settings, is_allowed
from ._scope import (
    DEV_SESSION_COOKIE,
    IamSessionVerifier,
    RequestScope,
    SessionVerifierT,
    VerifiedSession,
    decode_dev_session,
    resolve_scope,
)
from ._settings import EwsAuthSettings, auth_settings

__all__ = [
    'DEV_SESSION_COOKIE',
    'DirectoryMembership',
    'DirectoryOrganization',
    'DirectoryT',
    'DirectoryUser',
    'EwsAuthSettings',
    'IamSessionVerifier',
    'RequestScope',
    'SessionVerifierT',
    'SqlDirectory',
    'VerifiedSession',
    'auth_settings',
    'authorize',
    'configure_security',
    'current_scope',
    'current_settings',
    'decode_dev_session',
    'is_allowed',
    'resolve_scope',
]
