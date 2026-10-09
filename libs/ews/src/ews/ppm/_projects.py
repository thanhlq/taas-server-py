"""The single create path of a project (project API, intake *accept as project*): workflow process seeded from the
optional workflow template, default workflow, creator grant, ``ppm.project.created``."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import db.models.ews as ews_models
from db.models.ews.ews_enums import ProjectStatus
from foundation.db.types import DBAsyncScopedSession

from ews.security import RequestScope

from . import _access as access
from . import _events as events
from . import _workflow_service as wfs
from .repos import ProjectRepository, RepoFactory


def with_labels(p: ews_models.Project, labels: list[str] | None) -> None:
    """Store labels (trimmed, de-duplicated, order kept) in ``tags.labels``."""
    if labels is None:
        return
    clean = list(dict.fromkeys(label.strip() for label in labels if label.strip()))
    p.tags = {**(p.tags if isinstance(p.tags, dict) else {}), 'labels': clean}


async def create_project(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    *,
    name: str,
    template_id: str | None = None,
    locale: str | None = None,
    labels: list[str] | None = None,
    data: dict[str, Any] | None = None,
    **fields: Any,
) -> ews_models.Project:
    """A new project of the scope's organization; ``fields`` = project columns (``description``, ``code``,
    ``status``, dates, ``client_id``, ``user_id``, …). The caller checks ``ppm.project:create``."""
    repo = RepoFactory.get_repo(ProjectRepository, session)
    project = ews_models.Project(
        tenant_id=scope.tenant_id,
        organization_id=scope.organization_id,
        name=name,
        last_activity_at=datetime.now(UTC),
        **{k: v for k, v in fields.items() if v is not None},
    )
    project.status = project.status or ProjectStatus.NEW
    with_labels(project, labels)
    seed = wfs.seed_process(template_id, locale)
    seed.process.save(project)
    if template_id:
        project.default_view = project.default_view or 'kanban'
    created = await repo.add(project)
    await wfs.create_workflow(
        session,
        created,
        name=seed.workflow_name,
        stages=seed.stages,
        workflow_type=seed.workflow_type,
        is_default=True,
        template_id=seed.process.template_id,
    )
    await access.grant_creator(scope, created.id)
    await events.emit(
        session,
        scope,
        'ppm.project.created',
        'project',
        created.id,
        project_id=created.id,
        data={
            'name': created.name,
            'code': created.code,
            'kind': created.kind,
            'template_id': template_id,
            **(data or {}),
        },
    )
    return created
