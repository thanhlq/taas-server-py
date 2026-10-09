"""Drives (File-0100 §1, §3): the organization drive and *My files* are created lazily on first access; shared
drives by members with ``files.drive:create`` on the organization chain (the creator becomes ``drive_manager``)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from uuid import UUID

import msgspec
from db.models.files import FileDrive, FileNode
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException
from sqlalchemy import func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ews.security import RequestScope, is_allowed
from ews.shared import utcnow

from . import _access as access
from . import _delivery as delivery
from ._activity import record
from ._rules import clean_color
from .schemas import FileDriveCreate, FileDriveOut, FileDriveUpdate

PERSONAL_NAME = 'My files'


def _clean_drive_name(value: str | None) -> str:
    name = (value or '').strip()
    if not name:
        raise ClientException(detail='name is required')
    if len(name) > 120:
        raise ClientException(detail='name is longer than 120 characters')
    return name


async def _ensure(
    session: DBAsyncScopedSession, values: dict, index: list[str], where: str, lookup
) -> FileDrive:  # noqa: ANN001
    """Insert-or-skip on a partial unique index (concurrent first visits), then read the row."""
    drive = await session.scalar(lookup)
    if drive is not None:
        return drive
    now = utcnow()
    await session.execute(
        pg_insert(FileDrive)
        .values(id=uuid.uuid7(), created_at=now, updated_at=now, **values)
        .on_conflict_do_nothing(index_elements=index, index_where=text(where))
    )
    drive = await session.scalar(lookup)
    assert drive is not None
    return drive


async def ensure_organization_drive(
    session: DBAsyncScopedSession, scope: RequestScope
) -> FileDrive:
    """The drive of the request's organization (created on first access, File-0100)."""
    lookup = select(FileDrive).where(
        FileDrive.organization_id == scope.organization_id,
        FileDrive.kind == 'organization',
        FileDrive.deleted_at.is_(None),
    )
    return await _ensure(
        session,
        {
            'tenant_id': scope.tenant_id,
            'organization_id': scope.organization_id,
            'kind': 'organization',
            'name': scope.organization.name[:120],
            'settings': {'default_member_role': access.DEFAULT_MEMBER_ROLE},
        },
        ['organization_id'],
        "kind = 'organization' AND deleted_at IS NULL",
        lookup,
    )


async def ensure_personal_drive(
    session: DBAsyncScopedSession, scope: RequestScope
) -> FileDrive:
    """*My files* of the caller in the request's tenant (created on first access)."""
    lookup = select(FileDrive).where(
        FileDrive.tenant_id == scope.tenant_id,
        FileDrive.owner_id == scope.user_id,
        FileDrive.kind == 'personal',
        FileDrive.deleted_at.is_(None),
    )
    return await _ensure(
        session,
        {
            'tenant_id': scope.tenant_id,
            'owner_id': scope.user_id,
            'kind': 'personal',
            'name': PERSONAL_NAME,
            'settings': {},
        },
        ['tenant_id', 'owner_id'],
        "kind = 'personal' AND deleted_at IS NULL",
        lookup,
    )


async def visible_drives(
    session: DBAsyncScopedSession, scope: RequestScope
) -> list[access.DriveCtx]:
    """Drives listed for the caller in the request: the organization drive and shared drives of the request's
    organization it can read, drives of the tenant it holds a role on (shared with it), and *My files*."""
    org_drive = await ensure_organization_drive(session, scope)
    personal = await ensure_personal_drive(session, scope)
    org_read = await is_allowed(scope, access.DRIVE, 'read', scope.org_domains())
    granted = {} if scope.is_dev else await access.DRIVES.shared_with(scope.user_id)
    rows = list(
        await session.scalars(
            select(FileDrive)
            .where(
                FileDrive.tenant_id == scope.tenant_id,
                FileDrive.deleted_at.is_(None),
                FileDrive.kind.in_(('organization', 'shared', 'personal')),
                or_(
                    FileDrive.organization_id == scope.organization_id,
                    FileDrive.id.in_(list(granted)),
                    FileDrive.id == personal.id,
                ),
            )
            .order_by(FileDrive.kind, func.lower(FileDrive.name))
        )
    )
    org_ids = {d.organization_id for d in rows if d.organization_id}
    paths = await access.org_paths(session, scope, org_ids)
    member_of = (
        set()
        if scope.is_dev
        else await access.direct_member_of(session, scope, org_ids)
    )
    out: list[access.DriveCtx] = []
    for d in rows:
        if d.kind == 'personal':
            if d.id == personal.id:
                out.append(access.DriveCtx(d, '', 'drive_manager'))
            continue
        assert d.organization_id is not None
        implicit = (
            access.default_member_role(d)
            if d.kind == 'organization' and d.organization_id in member_of
            else None
        )
        in_request_org = d.organization_id == scope.organization_id
        if (in_request_org and org_read) or d.id in granted or implicit:
            out.append(access.DriveCtx(d, paths.get(d.organization_id, ''), implicit))
    order = {'organization': 0, 'shared': 1, 'personal': 2}
    out.sort(
        key=lambda c: (
            order[c.drive.kind],
            c.drive.id != org_drive.id,
            c.drive.name.lower(),
        )
    )
    return out


async def _usage(
    session: DBAsyncScopedSession, drive_ids: Sequence[UUID]
) -> dict[UUID, tuple[int, int]]:
    if not drive_ids:
        return {}
    rows = await session.execute(
        select(
            FileNode.drive_id, func.count(), func.coalesce(func.sum(FileNode.size), 0)
        )
        .where(
            FileNode.drive_id.in_(list(drive_ids)),
            FileNode.kind == 'file',
            FileNode.trashed_at.is_(None),
            FileNode.deleted_at.is_(None),
        )
        .group_by(FileNode.drive_id)
    )
    return {r[0]: (int(r[1]), int(r[2])) for r in rows}


async def drive_outputs(
    session: DBAsyncScopedSession, scope: RequestScope, ctxs: Sequence[access.DriveCtx]
) -> list[FileDriveOut]:
    usage = await _usage(session, [c.drive.id for c in ctxs])
    granted = {} if scope.is_dev else await access.DRIVES.shared_with(scope.user_id)
    out: list[FileDriveOut] = []
    for ctx in ctxs:
        d = ctx.drive
        count, size = usage.get(d.id, (0, 0))
        roles = [r for r in (granted.get(d.id), ctx.implicit_role) if r]
        out.append(
            FileDriveOut(
                id=str(d.id),
                kind=d.kind,  # type: ignore[arg-type]
                name=d.name,
                description=d.description,
                color=d.color,
                organization_id=str(d.organization_id) if d.organization_id else None,
                owner_id=str(d.owner_id) if d.owner_id else None,
                source_id=str(d.source_id) if d.source_id else None,
                default_member_role=access.default_member_role(d)
                if d.kind == 'organization'
                else None,
                sensitivity=delivery.sensitivity_of(d.settings),
                role=max(roles, key=access.DRIVES.rank) if roles else None,
                permissions=await access.permissions(scope, ctx),
                file_count=count,
                size=size,
                created_at=d.created_at,
                updated_at=d.updated_at,
            )
        )
    return out


async def create_shared_drive(
    session: DBAsyncScopedSession, scope: RequestScope, data: FileDriveCreate
) -> access.DriveCtx:
    """A shared drive of the request's organization; the creator becomes ``drive_manager``."""
    drive = FileDrive(
        id=uuid.uuid7(),
        tenant_id=scope.tenant_id,
        organization_id=scope.organization_id,
        kind='shared',
        name=_clean_drive_name(data.name),
        description=(data.description or '').strip()[:500] or None,
        color=clean_color(data.color),
        settings={},
        created_by=scope.user_id,
    )
    session.add(drive)
    await session.flush()
    await access.DRIVES.grant_creator(scope.user_id, drive.id)
    record(session, scope, drive.id, 'drive.created', name=drive.name)
    return access.DriveCtx(drive, scope.organization.path)


async def update_drive(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    ctx: access.DriveCtx,
    data: FileDriveUpdate,
) -> None:
    drive = ctx.drive
    if drive.kind == 'project':
        raise ClientException(
            detail="a project's files follow the project: change the project instead"
        )
    changed: dict[str, object] = {}
    if data.name is not None:
        if drive.kind == 'personal':
            raise ClientException(detail='My files cannot be renamed')
        drive.name = changed['name'] = _clean_drive_name(data.name)
    if data.description is not None:
        drive.description = (data.description or '').strip()[:500] or None
        changed['description'] = drive.description
    if data.color is not msgspec.UNSET:
        drive.color = changed['color'] = clean_color(data.color)
    if data.default_member_role is not None:
        if drive.kind != 'organization':
            raise ClientException(
                detail='default_member_role applies to organization drives only'
            )
        if data.default_member_role not in access.MEMBER_ROLES:
            raise ClientException(
                detail=f'default_member_role must be one of {", ".join(access.MEMBER_ROLES)}'
            )
        drive.settings = {
            **(drive.settings or {}),
            'default_member_role': data.default_member_role,
        }
        changed['default_member_role'] = data.default_member_role
    if data.sensitivity is not None and data.sensitivity != delivery.sensitivity_of(
        drive.settings
    ):
        if data.sensitivity not in delivery.SENSITIVITIES:
            raise ClientException(
                detail=f'sensitivity must be one of {", ".join(delivery.SENSITIVITIES)}'
            )
        drive.settings = {**(drive.settings or {}), 'sensitivity': data.sensitivity}
        changed['sensitivity'] = data.sensitivity
        revoke_links(drive)  # URLs handed out under the old policy stop working
    if changed:
        drive.updated_at = utcnow()
        record(session, scope, drive.id, 'drive.updated', **changed)
    await session.flush()


def revoke_links(drive: FileDrive) -> int:
    """Invalidate every outstanding signed URL of the drive (proxy delivery): bump ``url_epoch`` (File-0503)."""
    epoch = delivery.epoch_of(drive.settings) + 1
    drive.settings = {**(drive.settings or {}), 'url_epoch': epoch}
    drive.updated_at = utcnow()
    delivery.forget_link_states()
    return epoch


async def revoke_drive_links(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    ctx: access.DriveCtx,
    reason: str = 'manual',
) -> None:
    epoch = revoke_links(ctx.drive)
    record(
        session, scope, ctx.drive.id, 'drive.links_revoked', epoch=epoch, reason=reason
    )
    await session.flush()


async def delete_drive(
    session: DBAsyncScopedSession, scope: RequestScope, ctx: access.DriveCtx
) -> None:
    """Shared drives only: hidden at once, grants revoked; its files are purged with the trash retention."""
    drive = ctx.drive
    if drive.kind != 'shared':
        raise ClientException(detail='only shared drives can be deleted')
    drive.deleted_at = utcnow()
    delivery.forget_link_states()
    record(session, scope, drive.id, 'drive.deleted', name=drive.name)
    await session.flush()
    await access.DRIVES.forget(drive.id)
