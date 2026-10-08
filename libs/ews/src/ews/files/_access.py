"""Who may do what in the File Manager (taas-specs/files/file-manager-app-spec.md §3, File-0200 … File-0206).

Permissions are checked on the **drive** (RBAC domain ``drive:<id>``) with ``ews.access.ObjectAccess``:

| Drive | Domains | Implicit role |
| --- | --- | --- |
| organization | ``drive:<id>`` → the drive organization's chain → ``tenant:<id>`` | direct members of the organization: the drive's ``default_member_role`` (``drive_editor`` · ``drive_viewer``) |
| shared | same | none (explicit members; ``org_admin`` of the organization / an ancestor = everything) |
| personal | ``drive:<id>`` → ``tenant:<id>`` (no organization: org admins do not see *My files*) | the owner: ``drive_manager`` |

A drive / item the caller cannot read is a **404** (another organization's, tenant's or user's), **403** when it
can read it but lacks the action. Access that comes only from an ancestor organization or the tenant (oversight,
File-0200 / File-0201) is recorded in the activity (``admin.access``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from db.models.files import FileActivity, FileDrive, FileNode
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import NotFoundException
from sqlalchemy import select, text

from ews.access import ObjectAccess
from ews.authz import EwsResources, can
from ews.security import RequestScope
from ews.shared import parse_uuid, utcnow

DRIVE = EwsResources.FILES_DRIVE.value
ITEM = EwsResources.FILES_ITEM.value
MEMBER = EwsResources.FILES_MEMBER.value

DRIVES = ObjectAccess('drive', DRIVE, 'files', default_role='drive_editor')
MEMBER_ROLES = ('drive_editor', 'drive_viewer')
"""Allowed ``default_member_role`` of an organization drive (File-0200)."""
DEFAULT_MEMBER_ROLE = 'drive_editor'
OVERSIGHT_LOG_EVERY = timedelta(hours=1)


@dataclass(slots=True)
class DriveCtx:
    """A drive with what the permission checks need."""

    drive: FileDrive
    org_path: str
    """Materialized path of the drive's organization; ``''`` for a personal drive (no organization chain)."""
    implicit_role: str | None = None

    @property
    def kw(self) -> dict[str, str | None]:
        return {'implicit_role': self.implicit_role, 'org_path': self.org_path}


def default_member_role(drive: FileDrive) -> str:
    role = (drive.settings or {}).get('default_member_role')
    return role if role in MEMBER_ROLES else DEFAULT_MEMBER_ROLE


async def org_paths(
    session: DBAsyncScopedSession, scope: RequestScope, ids: set[UUID]
) -> dict[UUID, str]:
    """Paths of organizations of the caller's tenant (the request's own without a query)."""
    out: dict[UUID, str] = {}
    if scope.organization_id in ids:
        out[scope.organization_id] = scope.organization.path
    rest = [i for i in ids if i not in out]
    if rest:
        rows = await session.execute(
            text(
                'select id, path from taas_organizations where tenant_id = :t and id = any(:ids)'
            ),
            {'t': scope.tenant_id, 'ids': rest},
        )
        out.update({r.id: r.path for r in rows})
    return out


async def direct_member_of(
    session: DBAsyncScopedSession, scope: RequestScope, ids: set[UUID]
) -> set[UUID]:
    """The organizations among ``ids`` the caller is a direct member of (``taas_organization_members``)."""
    if not ids:
        return set()
    rows = await session.execute(
        text(
            'select organization_id from taas_organization_members where user_id = :u and organization_id = any(:ids)'
        ),
        {'u': scope.user_id, 'ids': list(ids)},
    )
    return {r.organization_id for r in rows}


async def drive_ctx(
    session: DBAsyncScopedSession, scope: RequestScope, drive: FileDrive
) -> DriveCtx:
    if drive.kind == 'personal':
        return DriveCtx(
            drive, '', 'drive_manager' if drive.owner_id == scope.user_id else None
        )
    org_id = drive.organization_id
    assert org_id is not None  # ck_taas_file_drives_owner
    path = (await org_paths(session, scope, {org_id})).get(org_id, '')
    implicit = None
    if (
        drive.kind == 'organization'
        and not scope.is_dev
        and await direct_member_of(session, scope, {org_id})
    ):
        implicit = default_member_role(drive)
    return DriveCtx(drive, path, implicit)


async def check(
    scope: RequestScope,
    ctx: DriveCtx,
    resource: str,
    action: str,
    *,
    what: str = 'drive',
) -> None:
    """404 when the caller cannot read the drive, 403 when it can but lacks ``resource:action``."""
    await DRIVES.check(scope, ctx.drive.id, resource, action, what=what, **ctx.kw)


async def allowed(
    scope: RequestScope, ctx: DriveCtx, resource: str, action: str
) -> bool:
    return await DRIVES.allowed(scope, ctx.drive.id, resource, action, **ctx.kw)


async def permissions(scope: RequestScope, ctx: DriveCtx) -> list[str]:
    return sorted(await DRIVES.permissions(scope, ctx.drive.id, **ctx.kw))


async def get_drive(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    drive_id: object,
    what: str = 'drive',
) -> FileDrive:
    """A live drive of the caller's tenant, no permission check (404 otherwise)."""
    did = parse_uuid(drive_id, what)
    drive = await session.scalar(
        select(FileDrive).where(
            FileDrive.id == did,
            FileDrive.tenant_id == scope.tenant_id,
            FileDrive.deleted_at.is_(None),
        )
    )
    if drive is None:
        raise NotFoundException(detail=f'{what} not found')
    return drive


async def load_drive(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    drive_id: object,
    resource: str = DRIVE,
    action: str = 'read',
) -> DriveCtx:
    """A drive the caller may ``resource:action`` (404 / 403)."""
    ctx = await drive_ctx(session, scope, await get_drive(session, scope, drive_id))
    await check(scope, ctx, resource, action)
    return ctx


async def load_node(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    node_id: object,
    resource: str = ITEM,
    action: str = 'read',
    *,
    trashed: bool | None = False,
) -> tuple[FileNode, DriveCtx]:
    """A folder / file the caller may ``resource:action`` (404 / 403). ``trashed``: ``False`` live only,
    ``True`` in the trash only, ``None`` both. Purged items are never returned."""
    nid = parse_uuid(node_id, 'item')
    node = await session.scalar(
        select(FileNode).where(
            FileNode.id == nid,
            FileNode.tenant_id == scope.tenant_id,
            FileNode.deleted_at.is_(None),
        )
    )
    if node is None or (
        trashed is not None and (node.trashed_at is not None) != trashed
    ):
        raise NotFoundException(detail='item not found')
    ctx = await drive_ctx(
        session, scope, await get_drive(session, scope, node.drive_id, 'item')
    )
    await check(scope, ctx, resource, action, what='item')
    return node, ctx


async def oversight(scope: RequestScope, ctx: DriveCtx) -> str | None:
    """``'ancestor'`` / ``'tenant'`` when the caller reads the drive only as an admin of an ancestor organization
    or of the tenant (no drive role, no implicit role, no role in the drive's organization), else ``None``."""
    if scope.is_dev or ctx.implicit_role:
        return None
    drive = ctx.drive
    orgs = [o for o in ctx.org_path.split('/') if o]
    direct = [DRIVES.domain(drive.id), *([f'org:{orgs[-1]}'] if orgs else [])]
    if await can(scope.user_id, direct, DRIVE, 'read'):
        return None
    ancestors = [f'org:{o}' for o in reversed(orgs[:-1])]
    if ancestors and await can(scope.user_id, ancestors, DRIVE, 'read'):
        return 'ancestor'
    return 'tenant'


async def log_oversight(
    session: DBAsyncScopedSession, scope: RequestScope, ctx: DriveCtx, what: str
) -> None:
    """Audit an oversight access (File-0201), at most once per hour per admin and drive."""
    via = await oversight(scope, ctx)
    if via is None:
        return
    since = utcnow() - OVERSIGHT_LOG_EVERY
    seen = await session.scalar(
        select(FileActivity.id)
        .where(
            FileActivity.drive_id == ctx.drive.id,
            FileActivity.actor_id == scope.user_id,
            FileActivity.action == 'admin.access',
            FileActivity.created_at >= since,
        )
        .limit(1)
    )
    if seen is None:
        session.add(
            FileActivity(
                tenant_id=scope.tenant_id,
                drive_id=ctx.drive.id,
                actor_id=scope.user_id,
                action='admin.access',
                detail={'via': via, 'what': what},
                created_at=utcnow(),
            )
        )
