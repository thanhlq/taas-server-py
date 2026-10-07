"""Who may do what on a project: permissions on ``project:<id>`` → organization chain → tenant
(taas-specs/ppm/ppm-app-spec.md Ppm-0001, Ppm-0002; authorization-rbac-spec §5).

Projects belong to the organization of the request (``/<org>/ppm``, ``X-Organization-Slug``). A project of another
organization, or one the caller may not read, is a 404 (no hint that it exists); a readable project without the
asked right is a 403. Tasks, workflows, task lists, iterations, comments and time logs are reached through their
project.
"""

from __future__ import annotations

from uuid import UUID

import db.models.ews as ews_models
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import (
    ClientException,
    NotFoundException,
    PermissionDeniedException,
)
from sqlalchemy import ColumnElement, and_, false, select

from ews.authz import EwsResources, ProjectRoles, grant, revoke_domain, user_domains
from ews.security import RequestScope, is_allowed
from ews.shared import parse_uuid

PROJECT = EwsResources.PROJECT.value
WORKFLOW = EwsResources.WORKFLOW.value
TASK = EwsResources.TASK.value
TASK_ACTIVITY = EwsResources.TASK_ACTIVITY.value


def project_domain(project_id: UUID | str) -> str:
    return f'project:{project_id}'


def project_domains(scope: RequestScope, project_id: UUID | str) -> list[str]:
    """RBAC domains of a project, most specific first: ``project:<id>`` → organization chain → tenant."""
    return [project_domain(project_id), *scope.org_domains()]


def in_scope(scope: RequestScope) -> ColumnElement[bool]:
    """SQL condition: the project belongs to the request's tenant and organization."""
    p = ews_models.Project
    return and_(
        p.tenant_id == scope.tenant_id,
        p.organization_id == scope.organization_id,
        p.deleted_at.is_(None),
    )


async def readable_projects(scope: RequestScope) -> ColumnElement[bool]:
    """SQL condition for project lists: in scope, and readable — every project with ``ppm.project:read`` on the
    organization chain (organization admins), else the projects the caller holds a role on."""
    p = ews_models.Project
    if await is_allowed(scope, PROJECT, 'read', scope.org_domains()):
        return in_scope(scope)
    ids: list[UUID] = []
    for domain in await user_domains(scope.user_id, 'project:'):
        try:
            ids.append(UUID(domain.removeprefix('project:')))
        except ValueError:
            continue
    return and_(in_scope(scope), p.id.in_(ids)) if ids else false()


async def require(
    scope: RequestScope, project_id: UUID | str, resource: str, action: str
) -> None:
    if not await is_allowed(
        scope, resource, action, project_domains(scope, project_id)
    ):
        raise PermissionDeniedException(
            detail=f'missing permission {resource}:{action}'
        )


async def require_create_project(scope: RequestScope) -> None:
    """``ppm.project:create`` on the organization chain (organization members and admins)."""
    if not await is_allowed(scope, PROJECT, 'create', scope.org_domains()):
        raise PermissionDeniedException(detail=f'missing permission {PROJECT}:create')


async def load_project(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    project_id: object,
    resource: str = PROJECT,
    action: str = 'read',
) -> ews_models.Project:
    """A project of the request's organization the caller may ``resource:action`` (404 / 403)."""
    pid = parse_uuid(project_id, 'project')
    project = await session.scalar(
        select(ews_models.Project).where(
            ews_models.Project.id == pid,
            in_scope(scope),
        )
    )
    if project is None:
        raise NotFoundException(detail='project not found')
    domains = project_domains(scope, project.id)
    if not await is_allowed(scope, resource, action, domains):
        if (resource, action) == (PROJECT, 'read') or not await is_allowed(
            scope, PROJECT, 'read', domains
        ):
            raise NotFoundException(detail='project not found')
        raise PermissionDeniedException(
            detail=f'missing permission {resource}:{action}'
        )
    return project


async def load_task(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    task_id: object,
    resource: str = TASK,
    action: str = 'read',
) -> tuple[ews_models.Task, ews_models.Project]:
    """A task of a project the caller may ``resource:action`` (404 outside the scope, 403 without the right)."""
    tid = parse_uuid(task_id, 'task')
    task = await session.scalar(
        select(ews_models.Task).where(
            ews_models.Task.id == tid, ews_models.Task.deleted_at.is_(None)
        )
    )
    if task is None or task.project_id is None:
        raise NotFoundException(detail='task not found')
    try:
        project = await load_project(session, scope, task.project_id, resource, action)
    except NotFoundException as error:
        raise NotFoundException(detail='task not found') from error
    return task, project


async def grant_creator(scope: RequestScope, project_id: UUID) -> None:
    """The creator of a project becomes its Project Admin (app-roles-spec §5)."""
    if not scope.is_dev:
        await grant(
            scope.user_id, ProjectRoles.PROJECT_ADMIN.value, project_domain(project_id)
        )


async def forget_project(project_id: UUID) -> None:
    """Drop every role grant on a deleted project."""
    await revoke_domain(project_domain(project_id))


def author(scope: RequestScope) -> str:
    """The author / owner value stored on comments and time logs: the session's e-mail (ids or e-mails until IAM
    profiles exist, ADR-12), never a value sent by the client."""
    return scope.email or str(scope.user_id)


async def workflow_viewer(scope: RequestScope, project_id: UUID) -> str | None:
    """Whose view of ``assigned`` workflows applies: ``None`` = every workflow (project / organization admins, i.e.
    ``ppm.workflow:update``), else the session user — never a user id sent by the client."""
    if not scope.is_dev and await is_allowed(
        scope, WORKFLOW, 'update', project_domains(scope, project_id)
    ):
        return None
    return author(scope)


def _ref_id(value: object, what: str) -> UUID | None:
    if value in (None, ''):
        return None
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError) as error:
        raise ClientException(detail=f'{what} must be a UUID') from error


async def task_refs(
    session: DBAsyncScopedSession,
    project_id: UUID,
    *,
    parent_id: object = None,
    task_list_id: object = None,
    iteration_id: object = None,
) -> dict[str, UUID | None]:
    """Parent task, task list and iteration of a task, checked to belong to the same project (400 otherwise):
    a request can never attach a task to another project's records."""
    checks = (
        ('parent_id', parent_id, ews_models.Task, 'parent task'),
        ('task_list_id', task_list_id, ews_models.TaskList, 'task list'),
        ('iteration_id', iteration_id, ews_models.ProjectIteration, 'iteration'),
    )
    refs: dict[str, UUID | None] = {}
    for key, value, model, what in checks:
        ref = _ref_id(value, what)
        if ref is not None:
            owner = await session.scalar(
                select(model.project_id).where(model.id == ref)
            )
            if owner != project_id:
                raise ClientException(detail=f'{what} not found in this project')
        refs[key] = ref
    return refs
