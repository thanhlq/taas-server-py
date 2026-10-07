"""Who calls and in which tenant / organization (taas-specs/iam/specs/authorization-rbac-spec.md §2).

``resolve_scope(headers, cookies)``:

1. Identity — ``iam``: the IAM verifies the session cookie / bearer token (``SessionVerifier``);
   ``dev``: the web's development sign-in cookie ``taas_dev_session`` (``{email, name}``).
2. User — ``taas_user_account.directory_id = sub`` (``iam``) or by e-mail (``dev``, optional).
3. Organization — ``X-Organization-Id``, else ``X-Organization-Slug`` (the ``/<org>/…`` segment of the web
   URL; slugs are unique, so the slug alone yields the organization and its tenant). The caller must be a
   member of it, of an ancestor, or Tenant Admin of its tenant. Without either: the root organization of
   ``X-Tenant-ID`` / the home tenant, else the first membership.
   ``X-Tenant-ID`` only selects among the caller's tenants: foreign → 404; mismatch with the
   organization → 400.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

import httpx
from foundation.exceptions import (
    ClientException,
    NotAuthorizedException,
    NotFoundException,
    PermissionDeniedException,
    ServiceUnavailableException,
)

from ._directory import DirectoryMembership, DirectoryOrganization, DirectoryT
from ._settings import EwsAuthSettings

DEV_SESSION_COOKIE = 'taas_dev_session'
DEV_ORGANIZATION_SLUG = 'demo'
"""Development sign-in organization of the web apps (``DEV_ORGANIZATION_SLUG`` in ``@taas/auth``)."""


@dataclass(frozen=True, slots=True)
class RequestScope:
    """The verified caller and the tenant / organization the request works in."""

    user_id: UUID
    email: str | None
    name: str | None
    tenant_id: UUID
    organization: DirectoryOrganization
    is_dev: bool = False

    @property
    def organization_id(self) -> UUID:
        return self.organization.id

    def org_domains(self) -> list[str]:
        """RBAC domains of the organization, most specific first: ``org:<id>`` → ancestors → tenant."""
        orgs = [o for o in self.organization.path.split('/') if o]
        return [*(f'org:{o}' for o in reversed(orgs)), f'tenant:{self.tenant_id}']


@dataclass(frozen=True, slots=True)
class VerifiedSession:
    sub: str
    email: str | None = None
    name: str | None = None


class SessionVerifierT(ABC):
    @abstractmethod
    async def verify(self, headers: Mapping[str, str]) -> VerifiedSession | None:
        """The session of the request's ``Cookie`` / ``Authorization`` headers, ``None`` when signed out."""


class IamSessionVerifier(SessionVerifierT):
    """Asks the TaaS IAM (``GET /api/v1/auth/session``: token claims only, cheap) with a short cache."""

    def __init__(self, iam_url: str, cache_seconds: int = 30, client: httpx.AsyncClient | None = None):
        self._url = f'{iam_url.rstrip("/")}/api/v1/auth/session'
        self._ttl = cache_seconds
        self._client = client
        self._cache: dict[str, tuple[float, VerifiedSession | None]] = {}

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=5.0)
        return self._client

    async def verify(self, headers: Mapping[str, str]) -> VerifiedSession | None:
        forward = {k: v for k in ('cookie', 'authorization') if (v := headers.get(k))}
        if not forward:
            return None
        key = hashlib.sha256(json.dumps(forward, sort_keys=True).encode()).hexdigest()
        now = time.monotonic()
        hit = self._cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
        try:
            res = await self._http().get(self._url, headers=forward)
        except httpx.HTTPError as error:
            raise ServiceUnavailableException(detail='identity service unreachable') from error
        if res.status_code in (401, 403):
            session = None
        elif res.status_code != 200:
            raise ServiceUnavailableException(detail=f'identity service answered {res.status_code}')
        else:
            body = res.json()
            sub = body.get('sub') if isinstance(body, dict) else None
            session = VerifiedSession(sub=sub, email=body.get('email'), name=body.get('name')) if sub else None
        if len(self._cache) > 10_000:
            self._cache.clear()
        self._cache[key] = (now + self._ttl, session)
        return session


def decode_dev_session(value: str | None) -> VerifiedSession | None:
    """``taas_dev_session`` = base64url(JSON ``{email, name}``) written by ``@taas/auth`` dev sign-in."""
    if not value:
        return None
    try:
        raw = value.replace('%3D', '=')
        padded = raw + '=' * (-len(raw) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded).decode())
    except (ValueError, UnicodeDecodeError):
        return None
    email = data.get('email') if isinstance(data, dict) else None
    if not isinstance(email, str) or not email:
        return None
    name = data.get('name') if isinstance(data.get('name'), str) else None
    return VerifiedSession(sub=f'dev:{email.lower()}', email=email, name=name or email)


def _uuid(value: str | None, header: str) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(value.strip())
    except ValueError as error:
        raise ClientException(detail=f'{header} must be a UUID') from error


_SLUG_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,39}$')
"""Organization slug of the web URL (``ORGANIZATION_SLUG_RE`` in ``@taas/auth``, lenient on length)."""


def _slug(value: str | None) -> str | None:
    slug = (value or '').strip().lower()
    if not slug:
        return None
    if not _SLUG_RE.match(slug):
        raise ClientException(detail='X-Organization-Slug is not a valid organization slug')
    return slug


async def _organization_id_of(
    directory: DirectoryT, organization_id: UUID | None, slug: str | None
) -> UUID | None:
    """``X-Organization-Id`` wins; else the organization of ``X-Organization-Slug`` (unknown → 404)."""
    if organization_id or not slug:
        return organization_id
    org = await directory.organization_by_slug(slug)
    if org is None:
        raise NotFoundException(detail='organization not found')
    return org.id


def _pick(
    memberships: list[DirectoryMembership], home_tenant: UUID | None, tenant: UUID | None
) -> DirectoryMembership | None:
    """The root-most membership of ``tenant`` (else of the home tenant), else the first one."""
    wanted = tenant or home_tenant
    in_tenant = [m for m in memberships if m.organization.tenant_id == wanted]
    if tenant and not in_tenant:
        raise NotFoundException(detail='tenant not found')
    pool = in_tenant or memberships
    return min(pool, key=lambda m: m.organization.depth) if pool else None


async def _organization_for(
    directory: DirectoryT,
    memberships: list[DirectoryMembership],
    organization_id: UUID,
) -> DirectoryOrganization:
    direct = next((m.organization for m in memberships if m.organization.id == organization_id), None)
    if direct:
        return direct
    org = await directory.organization(organization_id)
    if org is None:
        raise NotFoundException(detail='organization not found')
    ancestors = {o for o in org.path.split('/') if o}
    allowed = any(
        str(m.organization.id) in ancestors
        or (m.role == 'tenant_admin' and m.organization.tenant_id == org.tenant_id)
        for m in memberships
    )
    if not allowed:
        raise NotFoundException(detail='organization not found')
    return org


async def resolve_scope(
    settings: EwsAuthSettings,
    directory: DirectoryT,
    verifier: SessionVerifierT | None,
    headers: Mapping[str, str],
    cookies: Mapping[str, str],
) -> RequestScope:
    """Resolve and verify the caller of a request; raises 401 / 403 / 404 / 400 like the IAM."""
    tenant_id = _uuid(headers.get('x-tenant-id'), 'X-Tenant-ID')
    organization_id = _uuid(headers.get('x-organization-id'), 'X-Organization-Id')
    slug = _slug(headers.get('x-organization-slug'))

    if settings.mode == 'dev':
        session = decode_dev_session(cookies.get(DEV_SESSION_COOKIE))
        if session is None:
            raise NotAuthorizedException(detail='sign in required')
        return await _dev_scope(settings, directory, session, tenant_id, organization_id, slug)

    if verifier is None:
        raise ServiceUnavailableException(detail='identity service not configured')
    session = await verifier.verify(headers)
    if session is None:
        raise NotAuthorizedException(detail='sign in required')
    user = await directory.user_by_subject(session.sub)
    if user is None:
        raise PermissionDeniedException(detail='no directory account')
    memberships = await directory.memberships(user.id)
    organization_id = await _organization_id_of(directory, organization_id, slug)
    if organization_id:
        org = await _organization_for(directory, memberships, organization_id)
        if tenant_id and tenant_id != org.tenant_id:
            raise ClientException(detail='X-Tenant-ID does not match the organization')
    else:
        picked = _pick(memberships, user.tenant_id, tenant_id)
        if picked is None:
            raise PermissionDeniedException(detail='no organization membership')
        org = picked.organization
    return RequestScope(
        user_id=user.id,
        email=user.email or session.email,
        name=user.name or session.name,
        tenant_id=org.tenant_id,
        organization=org,
    )


async def _dev_scope(
    settings: EwsAuthSettings,
    directory: DirectoryT,
    session: VerifiedSession,
    tenant_id: UUID | None,
    organization_id: UUID | None,
    slug: str | None = None,
) -> RequestScope:
    """Development sign-in: trust the headers (organization id, else slug), else ``EWS_DEV_ORGANIZATION_ID``,
    else ``demo`` / the oldest root organization. The user is the directory account with that e-mail, if any."""
    org: DirectoryOrganization | None = None
    wanted = organization_id or _uuid(settings.dev_organization_id, 'EWS_DEV_ORGANIZATION_ID')
    if organization_id:
        org = await directory.organization(organization_id)
    elif slug:
        org = await directory.organization_by_slug(slug)
    if org is None and wanted:
        org = await directory.organization(wanted)
    if org is None:
        org = await directory.first_root_organization(DEV_ORGANIZATION_SLUG)
    if org is None:
        raise PermissionDeniedException(
            detail='development mode needs an organization: register a tenant or set EWS_DEV_ORGANIZATION_ID'
        )
    if tenant_id and tenant_id != org.tenant_id:
        raise ClientException(detail='X-Tenant-ID does not match the organization')
    email = session.email or ''
    user = await directory.user_by_email(email) if email else None
    user_id = user.id if user else uuid.uuid5(uuid.NAMESPACE_URL, f'taas-dev-user:{email.lower()}')
    return RequestScope(
        user_id=user_id,
        email=email or None,
        name=session.name,
        tenant_id=org.tenant_id,
        organization=org,
        is_dev=True,
    )
