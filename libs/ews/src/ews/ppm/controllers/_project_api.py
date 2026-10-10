"""Project and Task HTTP controllers (EWS PPM).

Thin controllers over the existing PPM repositories. A project is created with
or without a workflow template (its sticky *process*) and gets a default
workflow; tasks live in one workflow stage — rules in ``ews.ppm._workflow_service``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Optional
from uuid import UUID

import db.models.ews as ews_models
from advanced_alchemy.filters import LimitOffset, OrderBy, SearchFilter, StatementFilter
from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.http import BaseController, delete, get, patch, post, status
from foundation.http.response import PaginatedResponse, create_paginated_response
from foundation.exceptions import ClientException
from sqlalchemy import ColumnElement, and_, func, or_, select

from ews.security import RequestScope

from ews.security import current_scope
from ews import notifications

from .. import _access as access
from .. import _behaviours as behaviours
from .. import _workflow_service as wfs
from .. import workflow_catalog as catalog
from .._project_status import PROJECT_STATUS_CATALOG, project_status_color
from ..repos import ProjectRepository, RepoFactory
from .. import _events as events
from .. import _project_contacts as project_contacts
from .. import _projects as projects
from .. import _health as health
from .. import _work_items as items
from .. import _settings as ppm_settings
from ..schemas._project_api import (
    PROJECT_CLEARABLE_FIELDS,
    ProjectCreateRequest,
    ProjectListItem,
    ProjectResponse,
    ProjectStatusOption,
    ProjectUpdateRequest,
)


def _to_uuid(value: Optional[str]) -> Optional[UUID]:
    if not value:
        return None
    return value if isinstance(value, UUID) else UUID(str(value))


def _labels(p: ews_models.Project) -> list[str]:
    """Project labels, stored as ``tags = {'labels': [...]}``."""
    tags = p.tags if isinstance(p.tags, dict) else {}
    labels = tags.get('labels')
    return [str(label) for label in labels] if isinstance(labels, list) else []


def _project_fields(p: ews_models.Project) -> dict[str, Any]:
    """Fields shared by the list item and the detail response."""
    return {
        'id': str(p.id),
        'name': p.name,
        'code': p.code,
        'status': p.status,
        'status_color': project_status_color(p.status),
        'labels': _labels(p),
        'color': p.color,
        'icon_name': p.icon_name,
        'default_view': p.default_view,
        'starred': p.starred,
        'pinned': p.pinned,
        'start_date': p.start_date,
        'due_date': p.due_date,
        'created_at': getattr(p, 'created_at', None),
        'updated_at': getattr(p, 'updated_at', None),
        'description': p.description,
        'avatar_url': p.avatar_url,
        'user_id': p.user_id,
        'client_id': p.client_id,
        'last_activity_at': p.last_activity_at,
        'kind': p.kind or 'project',
    }


def _with_progress(
    fields: dict[str, Any], stats: Optional[tuple[int, int]]
) -> dict[str, Any]:
    total, done = stats or (0, 0)
    return {
        **fields,
        'task_count': total,
        'done_task_count': done,
        'progress': round(done * 100 / total) if total else 0,
    }


def project_editors(p: ews_models.Project, org: dict[str, Any]) -> dict[str, Any]:
    """Description editors of a project: its own setting, else the organization's (``editors``)."""
    own = (p.settings or {}).get('editors') if isinstance(p.settings, dict) else None
    return (
        own
        if isinstance(own, dict) and own.get('enabled')
        else org.get('editors') or ppm_settings.DEFAULT_SETTINGS['editors']
    )


async def _project_to_response(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    p: ews_models.Project,
    stats: Optional[tuple[int, int]] = None,
    locale: Optional[str] = None,
) -> ProjectResponse:
    process = wfs.ProjectProcess.of(p)
    template = (
        catalog.get_template(process.template_id, locale)
        if process.template_id
        else None
    )
    row = await ppm_settings.load(session, scope)
    org = ppm_settings.settings_of(row)
    ratings = (
        await health.latest_ratings(session, [p.id])
        if ppm_settings.capabilities_of(row).get('health')
        else {}
    )
    return ProjectResponse(
        **_with_progress(_project_fields(p), stats),
        health=ratings.get(p.id),
        permissions=sorted(await access.PROJECTS.permissions(scope, p.id)),
        role=None
        if scope.is_dev
        else await access.PROJECTS.role_of(scope.user_id, p.id),
        editors=project_editors(p, org),
        workflow=p.workflow,
        settings=p.settings,
        properties=p.properties,
        template_id=process.template_id,
        template_name=template['name'] if template else None,
        work_item_types=process.work_item_types,
        work_item_types_locked=process.work_item_types_locked,
        allowed_stage_types=process.allowed_stage_types,
        contacts=await project_contacts.contacts_of(session, p.id),
    )


def _project_to_list_item(
    p: ews_models.Project,
    stats: Optional[tuple[int, int]] = None,
    health_rating: Optional[str] = None,
) -> ProjectListItem:
    return ProjectListItem(
        **_with_progress(_project_fields(p), stats), health=health_rating
    )


def _now() -> datetime:
    """Naive UTC timestamp (``last_activity_at`` is a plain TIMESTAMP column)."""
    return datetime.now(UTC).replace(tzinfo=None)


async def _task_stats(
    session: DBAsyncScopedSession, project_ids: list[UUID]
) -> dict[UUID, tuple[int, int]]:
    """``{project_id: (tasks, done tasks)}`` — by stage type: a task is done in a
    *done*-band stage (or once completed); cancelled / rejected tasks do not count."""
    if not project_ids:
        return {}
    task = ews_models.Task
    done = func.count(task.id).filter(
        or_(
            task.stage_type.in_(catalog.done_stage_types()),
            task.completed_at.is_not(None),
        )
    )
    counted = and_(
        or_(
            task.stage_type.is_(None),
            task.stage_type.not_in(catalog.excluded_stage_types()),
        ),
        or_(
            task.behaviour.is_(None), task.behaviour.not_in(behaviours.NOT_IN_PROGRESS)
        ),
    )
    result = await session.execute(
        select(task.project_id, func.count(task.id), done)
        .where(task.project_id.in_(project_ids), task.deleted_at.is_(None), counted)
        .group_by(task.project_id)
    )
    return {row[0]: (int(row[1]), int(row[2])) for row in result.all()}


# Record activity on a project (Ppm-0007) — one implementation for every controller.
_touch_project = items.touch_project


_TRACKED_PROJECT_FIELDS = (
    'name',
    'code',
    'description',
    'status',
    'start_date',
    'due_date',
    'color',
    'icon_name',
    'default_view',
    'user_id',
    'client_id',
)


def _merged_project_settings(
    p: ews_models.Project, patch: dict[str, Any]
) -> dict[str, Any]:
    """Project settings after a PATCH (null = inherit / default).

    ``editors`` validated like the organization's; ``notifications.off`` = PPM kinds switched off for the project
    (Ppm-1713; mandatory kinds cannot be).
    """
    current = dict(p.settings) if isinstance(p.settings, dict) else {}
    for key, value in patch.items():
        if key not in ('editors', 'notifications'):
            raise ClientException(detail=f'unknown project setting {key!r}')
        if value is None:
            current.pop(key, None)
        elif key == 'editors':
            current['editors'] = ppm_settings.clean_settings({'editors': value})[
                'editors'
            ]
        else:
            current['notifications'] = {'off': _muted_kinds(value)}
    return current


def _muted_kinds(value: Any) -> list[str]:
    off = value.get('off') if isinstance(value, dict) else None
    if not isinstance(off, list):
        raise ClientException(detail='notifications.off must be a list of kinds')
    kinds = {k.key: k for k in notifications.all_kinds('ppm')}
    for key in off:
        kind = kinds.get(key) if isinstance(key, str) else None
        if kind is None:
            raise ClientException(detail=f'unknown notification kind {key!r}')
        if kind.mandatory:
            raise ClientException(detail=f'{key} cannot be switched off')
    return sorted(set(off))


class ProjectController(BaseController):
    """Projects: create (with/without template), list, detail, update, delete."""

    api_prefix = '/api/v1/projects'
    tags = ('Projects',)

    @get('/')
    @db_context_session
    async def list_projects(
        self,
        session: DBAsyncScopedSession,
        limit: int = 50,
        offset: int = 0,
        q: Optional[str] = None,
        kind: str = 'project',
    ) -> PaginatedResponse[ProjectListItem]:
        """Projects of the request's organization the caller may read; ``q`` searches name, code and
        description (case-insensitive). ``kind``: ``project`` (default) or ``template`` (Ppm-0880); personal
        projects (Inboxes) are never listed."""
        scope = await current_scope()
        if kind not in ('project', 'template'):
            raise ClientException(detail='kind must be project or template')
        repo = RepoFactory.get_repo(ProjectRepository, session)
        filters: list[StatementFilter | ColumnElement[bool]] = [
            LimitOffset(limit=limit, offset=offset),
            OrderBy(field_name='id', sort_order='desc'),
            await access.readable_projects(scope),
            ews_models.Project.kind == kind,
        ]
        if q and q.strip():
            filters.append(
                SearchFilter(
                    field_name={'name', 'code', 'description'},
                    value=q.strip(),
                    ignore_case=True,
                )
            )
        rows, total = await repo.list_and_count(*filters)
        stats = await _task_stats(session, [p.id for p in rows])
        ratings = (
            await health.latest_ratings(session, [p.id for p in rows])
            if await ppm_settings.enabled(session, scope, 'health')
            else {}
        )
        return create_paginated_response(
            [
                _project_to_list_item(p, stats.get(p.id), ratings.get(p.id))
                for p in rows
            ],
            total=total,
        )

    @get('/statuses')
    async def list_project_statuses(self) -> list[ProjectStatusOption]:
        """The project status catalog: every status with its badge colour and group."""
        await current_scope()
        return [
            ProjectStatusOption(
                value=status.value, color=color.value, group=group.value
            )
            for status, (color, group) in PROJECT_STATUS_CATALOG.items()
        ]

    @get('/{project_id}')
    @db_context_session(auto_commit=True)
    async def get_project(
        self,
        project_id: str,
        session: DBAsyncScopedSession,
        locale: Optional[str] = None,
    ) -> ProjectResponse:
        scope = await current_scope()
        p = await access.load_project(session, scope, project_id)
        # Projects made before workflows existed get their process + default workflow now.
        await wfs.ensure_workflows(session, p)
        stats = await _task_stats(session, [p.id])
        return await _project_to_response(session, scope, p, stats.get(p.id), locale)

    @post('/', status_code=status.HTTP_201_CREATED)
    @db_context_session(auto_commit=True)
    async def create_project(
        self, data: ProjectCreateRequest, session: DBAsyncScopedSession
    ) -> ProjectResponse:
        scope = await current_scope()
        await access.require_create_project(scope)
        created = await projects.create_project(
            session,
            scope,
            name=data.name,
            template_id=data.template_id,
            locale=data.locale,
            labels=data.labels,
            description=data.description,
            code=data.code,
            status=data.status,
            start_date=data.start_date,
            due_date=data.due_date,
            color=data.color,
            icon_name=data.icon_name,
            default_view=data.default_view,
            client_id=await project_contacts.check_client(
                session, scope, data.client_id
            ),
            user_id=data.user_id,
        )
        if data.contact_ids:
            await project_contacts.set_contacts(
                session, scope, created, data.contact_ids, data.default_contact_id
            )
        return await _project_to_response(session, scope, created, locale=data.locale)

    @patch('/{project_id}')
    @db_context_session(auto_commit=True)
    async def update_project(
        self, project_id: str, data: ProjectUpdateRequest, session: DBAsyncScopedSession
    ) -> ProjectResponse:
        repo = RepoFactory.get_repo(ProjectRepository, session)
        scope = await current_scope()
        p = await access.load_project(
            session, scope, project_id, access.PROJECT, 'update'
        )
        before = events.snapshot(p, _TRACKED_PROJECT_FIELDS) | {'labels': _labels(p)}
        fields = data.as_dict()
        clear = set(fields.pop('clear', None) or [])
        unknown = clear - PROJECT_CLEARABLE_FIELDS
        if unknown:
            raise ClientException(detail=f'cannot clear {", ".join(sorted(unknown))}')
        contact_ids = fields.pop('contact_ids', None)
        default_contact = fields.pop('default_contact_id', None)
        if 'client_id' in fields:
            fields['client_id'] = await project_contacts.check_client(
                session, scope, fields['client_id']
            )
        if contact_ids is not None or default_contact is not None:
            current = [
                c['id'] for c in await project_contacts.contacts_of(session, p.id)
            ]
            await project_contacts.set_contacts(
                session,
                scope,
                p,
                current if contact_ids is None else contact_ids,
                default_contact,
            )
        settings_patch = fields.pop('settings', None)
        if settings_patch is not None:
            p.settings = _merged_project_settings(p, settings_patch)
        projects.with_labels(p, fields.pop('labels', None))
        work_item_types = fields.pop('work_item_types', None)
        if work_item_types is not None:
            await wfs.ensure_workflows(session, p)
            process = wfs.ProjectProcess.of(p)
            process.work_item_types = wfs.checked_work_item_types(
                process, work_item_types, p
            )
            process.save(p)
        for field, value in fields.items():
            setattr(p, field, value)
        for field in clear:
            setattr(p, field, None)
        p.last_activity_at = _now()
        updated = await repo.update(p)
        changes = events.diff(
            before,
            events.snapshot(updated, _TRACKED_PROJECT_FIELDS)
            | {'labels': _labels(updated)},
        )
        if changes or settings_patch is not None:
            await events.emit(
                session,
                scope,
                'ppm.project.updated',
                'project',
                updated.id,
                project_id=updated.id,
                changes=changes,
                data={'name': updated.name, 'code': updated.code},
            )
        stats = await _task_stats(session, [updated.id])
        return await _project_to_response(
            session, scope, updated, stats.get(updated.id)
        )

    @delete('/{project_id}', status_code=status.HTTP_204_NO_CONTENT)
    @db_context_session(auto_commit=True)
    async def delete_project(
        self, project_id: str, session: DBAsyncScopedSession
    ) -> None:
        scope = await current_scope()
        project = await access.load_project(
            session, scope, project_id, access.PROJECT, 'delete'
        )
        # Soft delete (audit, Ppm-0011): the project and everything in it stay in the database, unreachable.
        project.deleted_at = datetime.now(UTC)
        await session.flush()
        pid = project.id
        await events.emit(
            session,
            scope,
            'ppm.project.deleted',
            'project',
            pid,
            project_id=pid,
            data={'name': project.name, 'code': project.code},
        )
        await access.forget_project(pid)
