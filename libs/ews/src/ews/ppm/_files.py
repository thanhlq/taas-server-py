"""Files of projects and items (work-model Ppm-0840…0843, File-0101 / File-0102): one File Manager **source drive**
per project (``kind = project``) holding the project files at its root and the item attachments in
``Tasks/<code>``. Access comes from PPM: ``ppm.project:update`` → ``drive_manager``, ``ppm.task:update`` →
``drive_editor``, readers → ``drive_viewer`` — so uploads, versions, previews and signed delivery are the File
Manager's. Web links are ``taas_ppm_attachments`` rows (kind ``link``)."""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlparse

import db.models.ews as ews_models
from db.models.files import FileDrive
from db.models.ppm import PpmAttachment
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException, NotFoundException
from sqlalchemy import func, select

from ews.files import ensure_source_drive, ensure_source_folder, register_source
from ews.security import RequestScope
from ews.shared import parse_uuid

from . import _events as events
from ._access import PROJECTS, author

TASKS_FOLDER = 'Tasks'


async def _drive_role(
    session: DBAsyncScopedSession, scope: RequestScope, drive: FileDrive
) -> str | None:
    project = await session.scalar(
        select(ews_models.Project).where(
            ews_models.Project.id == drive.source_id,
            ews_models.Project.tenant_id == scope.tenant_id,
            ews_models.Project.deleted_at.is_(None),
        )
    )
    if project is None:
        return None
    granted = await PROJECTS.permissions(scope, project.id)
    if 'ppm.project:update' in granted:
        return 'drive_manager'
    if 'ppm.task:update' in granted:
        return 'drive_editor'
    if 'ppm.project:read' in granted:
        return 'drive_viewer'
    return None


register_source('project', _drive_role)


async def project_drive(
    session: DBAsyncScopedSession, project: ews_models.Project
) -> FileDrive:
    assert project.tenant_id is not None and project.organization_id is not None
    return await ensure_source_drive(
        session,
        kind='project',
        tenant_id=project.tenant_id,
        organization_id=project.organization_id,
        source_id=project.id,
        name=project.name or 'Project',
    )


async def task_folder(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    project: ews_models.Project,
    task: ews_models.Task,
) -> tuple[FileDrive, str | None]:
    """``(drive, folder id)`` of an item's attachments (``Tasks/<code>``)."""
    drive = await project_drive(session, project)
    folder = await ensure_source_folder(
        session, scope, drive, [TASKS_FOLDER, task.code or str(task.id)]
    )
    return drive, str(folder.id) if folder is not None else None


# --- web links ------------------------------------------------------------------------------------


def _clean_url(value: str) -> str:
    url = (value or '').strip()
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        raise ClientException(detail='a link needs an http(s) address')
    if len(url) > 2048:
        raise ClientException(detail='the address is too long')
    return url


async def links(
    session: DBAsyncScopedSession, project_id: object, task_id: object | None
) -> list[PpmAttachment]:
    a = PpmAttachment
    query = select(a).where(
        a.project_id == project_id, a.kind == 'link', a.deleted_at.is_(None)
    )
    query = (
        query.where(a.task_id == task_id)
        if task_id
        else query.where(a.task_id.is_(None))
    )
    return list((await session.scalars(query.order_by(a.position, a.created_at))).all())


async def add_link(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    project: ews_models.Project,
    task: ews_models.Task | None,
    *,
    url: str,
    title: str | None,
) -> PpmAttachment:
    clean = _clean_url(url)
    last = await session.scalar(
        select(func.max(PpmAttachment.position)).where(
            PpmAttachment.project_id == project.id,
            PpmAttachment.task_id == task.id
            if task
            else PpmAttachment.task_id.is_(None),
        )
    )
    link = PpmAttachment(
        tenant_id=scope.tenant_id,
        project_id=project.id,
        task_id=task.id if task else None,
        kind='link',
        url=clean,
        title=((title or '').strip() or urlparse(clean).netloc)[:300],
        position=(last or 0) + 1,
        added_by=author(scope),
    )
    session.add(link)
    await session.flush()
    await events.emit(
        session,
        scope,
        'ppm.attachment.added',
        'task' if task else 'project',
        task.id if task else project.id,
        project_id=project.id,
        data={
            'attachment_id': str(link.id),
            'kind': 'link',
            'title': link.title,
            'url': clean,
        },
    )
    return link


async def remove_link(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    project: ews_models.Project,
    task: ews_models.Task | None,
    link_id: str,
) -> None:
    a = PpmAttachment
    link = await session.scalar(
        select(a).where(
            a.id == parse_uuid(link_id, 'link'),
            a.project_id == project.id,
            a.task_id == task.id if task else a.task_id.is_(None),
            a.deleted_at.is_(None),
        )
    )
    if link is None:
        raise NotFoundException(detail='link not found')
    link.deleted_at = datetime.now(UTC)
    await session.flush()
    await events.emit(
        session,
        scope,
        'ppm.attachment.removed',
        'task' if task else 'project',
        task.id if task else project.id,
        project_id=project.id,
        data={'attachment_id': str(link.id), 'kind': 'link', 'title': link.title},
    )
