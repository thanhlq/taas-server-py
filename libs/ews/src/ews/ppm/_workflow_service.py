"""Project workflow rules (framework-free).

Model (``taas-specs/ppm/project/project-workflow/README.md``):

- **Process** (per project, stored in ``Project.workflow``): the template the
  project was created from (sticky, optional), its work item types and the
  allowed stage types. Without a template the project is unconstrained.
- **Workflows** (``Workflow`` rows, many per project): boards of ordered stages.
  Exactly one is the project default (``is_default``); privacy is ``all``
  (every project member) or ``assigned`` (only its assigned users, stored as
  ``ProjectWorkflowAssignment`` rows).
- **Stages** (``WorkflowStage``): a custom name + a canonical ``stage_type``
  that must be allowed by the process. One stage per workflow is the default
  landing stage for new tasks.
- **Tasks** belong to one workflow and one of its stages; ``Task.stage_type``
  mirrors the stage's type so progress / analytics work across workflows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Optional
from uuid import UUID

import db.models.ews as ews_models
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException, NotFoundException
from foundation.types.types import SimpleStatus
from sqlalchemy import func, select, update

from . import workflow_catalog as catalog

PRIVACY_ALL = 'all'
PRIVACY_ASSIGNED = 'assigned'
PRIVACIES = frozenset({PRIVACY_ALL, PRIVACY_ASSIGNED})

# Board of a project created without a template.
DEFAULT_STAGES: list[dict[str, Any]] = [
    {'name': 'To Do', 'stage_type': 'new', 'is_default': True},
    {'name': 'In Progress', 'stage_type': 'in_progress'},
    {'name': 'Review', 'stage_type': 'review'},
    {'name': 'Done', 'stage_type': 'done'},
]
# Board of projects created before workflows existed (their ``Project.workflow.stages``
# is used when present).
LEGACY_DEFAULT_STAGES: list[dict[str, Any]] = [
    {'name': 'Backlog', 'stage_type': 'backlog', 'is_default': True},
    {'name': 'In Progress', 'stage_type': 'in_progress'},
    {'name': 'Review', 'stage_type': 'review'},
    {'name': 'Done', 'stage_type': 'done'},
]
# Work item types of a project without a template (taken from the universal template).
DEFAULT_WORK_ITEM_KEYS = [
    'task',
    'milestone',
    'deliverable',
    'action_item',
    'bug',
    'issue',
    'risk',
    'change_request',
    'meeting',
    'documentation',
]
UNIVERSAL_TEMPLATE_ID = 'universal.general'


def now() -> datetime:
    """Naive UTC timestamp (TIMESTAMP columns)."""
    return datetime.now(UTC).replace(tzinfo=None)


def to_uuid(value: Any) -> Optional[UUID]:
    if not value:
        return None
    return value if isinstance(value, UUID) else UUID(str(value))


# ── Process ───────────────────────────────────────────────────────────────────


@dataclass
class ProjectProcess:
    """A project's workflow constraints (``Project.workflow`` JSON)."""

    template_id: Optional[str] = None
    category: Optional[str] = None
    work_item_types: list[dict[str, Any]] = field(default_factory=list)
    # True when the template fixes the work item types (subset only, no new keys).
    work_item_types_locked: bool = False
    # None = any stage type.
    allowed_stage_types: Optional[list[str]] = None

    @classmethod
    def of(cls, project: ews_models.Project) -> 'ProjectProcess':
        data = project.workflow if isinstance(project.workflow, dict) else {}
        allowed = data.get('allowed_stage_types')
        return cls(
            template_id=data.get('template_id') or None,
            category=data.get('category') or None,
            work_item_types=list(data.get('work_item_types') or []),
            work_item_types_locked=bool(data.get('work_item_types_locked')),
            allowed_stage_types=list(allowed) if isinstance(allowed, list) else None,
        )

    @property
    def initialized(self) -> bool:
        return bool(self.work_item_types) or self.allowed_stage_types is not None

    def save(self, project: ews_models.Project) -> None:
        data = project.workflow if isinstance(project.workflow, dict) else {}
        data = {
            k: v for k, v in data.items() if k != 'stages'
        }  # legacy board, now Workflow rows
        project.workflow = {
            **data,
            'template_id': self.template_id,
            'category': self.category,
            'work_item_types': self.work_item_types,
            'work_item_types_locked': self.work_item_types_locked,
            'allowed_stage_types': self.allowed_stage_types,
        }

    def allows_stage_type(self, key: str) -> bool:
        return self.allowed_stage_types is None or key in self.allowed_stage_types

    def check_stage_type(self, key: Optional[str]) -> str:
        if not key or not catalog.is_stage_type(key):
            raise ClientException(detail=f"Unknown stage type '{key}'.")
        if not self.allows_stage_type(key):
            raise ClientException(
                detail=f"Stage type '{key}' is not allowed by the project's workflow template."
            )
        return key

    def work_item_keys(self) -> list[str]:
        return [w['key'] for w in self.work_item_types]

    def check_work_item_type(self, key: Optional[str]) -> Optional[str]:
        if not key:
            return None
        if self.work_item_types_locked and key not in self.work_item_keys():
            raise ClientException(
                detail=f"Work item type '{key}' is not part of the project's workflow template."
            )
        return key

    def default_work_item_type(self) -> str:
        keys = self.work_item_keys()
        return 'task' if not keys or 'task' in keys else keys[0]


def _template_process(template: dict[str, Any]) -> ProjectProcess:
    locked = bool(template['work_item_types'])
    types = template['work_item_types'] if locked else _default_work_item_types(None)
    return ProjectProcess(
        template_id=template['id'],
        category=template['category'],
        work_item_types=types,
        work_item_types_locked=locked,
        allowed_stage_types=list(template['allowed_stage_types']),
    )


def _default_work_item_types(locale: Optional[str]) -> list[dict[str, Any]]:
    universal = catalog.get_template(UNIVERSAL_TEMPLATE_ID, locale) or {
        'work_item_types': []
    }
    by_key = {w['key']: w for w in universal['work_item_types']}
    return [by_key[k] for k in DEFAULT_WORK_ITEM_KEYS if k in by_key]


@dataclass
class ProcessSeed:
    process: ProjectProcess
    workflow_name: str
    workflow_type: str
    stages: list[dict[str, Any]]


def seed_process(template_id: Optional[str], locale: Optional[str]) -> ProcessSeed:
    """Process + default board of a new project (localized stage names / terms)."""
    template = catalog.get_template(template_id, locale) if template_id else None
    if template_id and template is None:
        raise ClientException(detail=f"Unknown workflow template '{template_id}'.")
    if template is None:
        return ProcessSeed(
            process=ProjectProcess(work_item_types=_default_work_item_types(locale)),
            workflow_name=catalog.label('main_workflow', 'Main workflow', locale),
            workflow_type='kanban',
            stages=[
                {**s, 'name': catalog.localized_stage_name(s['name'], locale)}
                for s in DEFAULT_STAGES
            ],
        )
    process = _template_process(template)
    if not template['work_item_types']:
        process.work_item_types = _default_work_item_types(locale)
    return ProcessSeed(
        process=process,
        workflow_name=template['name'],
        workflow_type=template.get('workflow_type') or 'kanban',
        stages=template['stages'],
    )


# ── Workflows ─────────────────────────────────────────────────────────────────


async def load_workflows(
    session: DBAsyncScopedSession, project_id: UUID
) -> list[ews_models.Workflow]:
    wf = ews_models.Workflow
    rows = await session.scalars(
        select(wf)
        .where(wf.project_id == project_id)
        .order_by(wf.is_default.desc().nulls_last(), wf.display_order, wf.id)
    )
    return list(rows.all())


async def load_stages(
    session: DBAsyncScopedSession, workflow_ids: list[UUID]
) -> dict[UUID, list[ews_models.WorkflowStage]]:
    out: dict[UUID, list[ews_models.WorkflowStage]] = {wid: [] for wid in workflow_ids}
    if not workflow_ids:
        return out
    st = ews_models.WorkflowStage
    rows = await session.scalars(
        select(st)
        .where(st.workflow_id.in_(workflow_ids), st.deleted_at.is_(None))
        .order_by(st.display_order, st.id)
    )
    for s in rows.all():
        out.setdefault(s.workflow_id, []).append(s)
    return out


async def load_assignments(
    session: DBAsyncScopedSession, workflow_ids: list[UUID]
) -> dict[UUID, list[str]]:
    out: dict[UUID, list[str]] = {wid: [] for wid in workflow_ids}
    if not workflow_ids:
        return out
    a = ews_models.ProjectWorkflowAssignment
    rows = await session.scalars(
        select(a)
        .where(
            a.workflow_id.in_(workflow_ids),
            a.deleted_at.is_(None),
            a.user_id.is_not(None),
        )
        .order_by(a.priority, a.id)
    )
    for row in rows.all():
        out.setdefault(row.workflow_id, []).append(row.user_id)
    return out


async def stage_task_counts(
    session: DBAsyncScopedSession, workflow_ids: list[UUID]
) -> dict[UUID, int]:
    if not workflow_ids:
        return {}
    t = ews_models.Task
    result = await session.execute(
        select(t.stage_id, func.count(t.id))
        .where(t.workflow_id.in_(workflow_ids), t.deleted_at.is_(None))
        .group_by(t.stage_id)
    )
    return {row[0]: int(row[1]) for row in result.all() if row[0] is not None}


def default_stage(
    stages: list[ews_models.WorkflowStage],
) -> Optional[ews_models.WorkflowStage]:
    return next((s for s in stages if s.is_default), stages[0] if stages else None)


def stage_for_type(
    stages: list[ews_models.WorkflowStage], stage_type: Optional[str]
) -> Optional[ews_models.WorkflowStage]:
    """First stage of a workflow with this stage type (tasks keep their lifecycle when moved)."""
    return next((s for s in stages if s.stage_type == stage_type), None)


def normalize_privacy(value: Optional[str]) -> str:
    return PRIVACY_ASSIGNED if value == PRIVACY_ASSIGNED else PRIVACY_ALL


def visible_to(
    workflow: ews_models.Workflow,
    assigned: list[str],
    user_id: Optional[str],
    project: ews_models.Project,
) -> bool:
    """Privacy ``assigned``: only its assigned users (and the project's responsible user)."""
    if user_id is None or normalize_privacy(workflow.privacy) == PRIVACY_ALL:
        return True
    return user_id in assigned or (project.user_id or '') == user_id


def new_stage(
    workflow: ews_models.Workflow, spec: dict[str, Any], order: int
) -> ews_models.WorkflowStage:
    return ews_models.WorkflowStage(
        workflow_id=workflow.id,
        project_id=workflow.project_id,
        name=spec['name'],
        description=spec.get('description'),
        stage_type=spec['stage_type'],
        color=spec.get('color') or catalog.stage_type_tone(spec['stage_type']),
        wip_limit=spec.get('wip_limit'),
        is_default=bool(spec.get('is_default')),
        display_order=order,
        position=order,
        status=SimpleStatus.ACTIVE,
    )


async def create_workflow(
    session: DBAsyncScopedSession,
    project: ews_models.Project,
    *,
    name: str,
    stages: list[dict[str, Any]],
    workflow_type: str = 'kanban',
    description: Optional[str] = None,
    privacy: str = PRIVACY_ALL,
    is_default: bool = False,
    template_id: Optional[str] = None,
) -> tuple[ews_models.Workflow, list[ews_models.WorkflowStage]]:
    """A workflow with its stages (one default stage guaranteed)."""
    if not stages:
        raise ClientException(detail='A workflow needs at least one stage.')
    order = await session.scalar(
        select(func.coalesce(func.max(ews_models.Workflow.display_order), -1)).where(
            ews_models.Workflow.project_id == project.id
        )
    )
    workflow = ews_models.Workflow(
        project_id=project.id,
        name=name.strip(),
        description=description,
        workflow_type=workflow_type,
        scope='project',
        privacy=normalize_privacy(privacy),
        is_default=is_default,
        template_id=template_id,
        display_order=int(order or 0) + 1,
        status=SimpleStatus.ACTIVE,
    )
    session.add(workflow)
    await session.flush()
    if not any(s.get('is_default') for s in stages):
        stages = [{**stages[0], 'is_default': True}, *stages[1:]]
    rows = [new_stage(workflow, spec, i) for i, spec in enumerate(stages)]
    session.add_all(rows)
    await session.flush()
    return workflow, rows


async def ensure_workflows(
    session: DBAsyncScopedSession, project: ews_models.Project
) -> list[ews_models.Workflow]:
    """The project's workflows; creates the default one (and migrates its tasks) for
    projects made before workflows existed. Idempotent."""
    workflows = await load_workflows(session, project.id)
    process = ProjectProcess.of(project)
    if workflows:
        if not any(w.is_default for w in workflows):
            workflows[0].is_default = True
        return workflows

    data = project.workflow if isinstance(project.workflow, dict) else {}
    template = (
        catalog.get_template(process.template_id) if process.template_id else None
    )
    legacy = data.get('stages') if isinstance(data.get('stages'), list) else None
    if legacy:
        stages = [
            {
                'name': s.get('name') or s.get('stage_type'),
                'stage_type': s.get('stage_type')
                if catalog.is_stage_type(s.get('stage_type'))
                else 'in_progress',
                'color': s.get('tone'),
            }
            for s in sorted(legacy, key=lambda s: s.get('order') or 0)
            if s.get('stage_type')
        ]
    elif template:
        stages = template['stages']
    else:
        stages = LEGACY_DEFAULT_STAGES

    if not process.initialized:
        if template:
            process = _template_process(template)
        else:
            process = ProjectProcess(
                template_id=None, work_item_types=_default_work_item_types(None)
            )
        if process.allowed_stage_types is not None:
            for s in stages:
                if s['stage_type'] not in process.allowed_stage_types:
                    process.allowed_stage_types.append(s['stage_type'])
        process.save(project)

    workflow, rows = await create_workflow(
        session,
        project,
        name=template['name']
        if template
        else catalog.label('main_workflow', 'Main workflow'),
        stages=stages,
        workflow_type=(template or {}).get('workflow_type') or 'kanban',
        is_default=True,
        template_id=process.template_id,
    )
    await attach_orphan_tasks(session, project.id, workflow, rows)
    return [workflow]


async def attach_orphan_tasks(
    session: DBAsyncScopedSession,
    project_id: UUID,
    workflow: ews_models.Workflow,
    stages: list[ews_models.WorkflowStage],
) -> None:
    """Put tasks without a workflow into ``workflow``, matching stages by stage type."""
    fallback = default_stage(stages)
    if fallback is None:
        return
    t = ews_models.Task
    by_type: dict[str, ews_models.WorkflowStage] = {}
    for s in stages:
        by_type.setdefault(s.stage_type, s)
    for stage_type, stage in by_type.items():
        await session.execute(
            update(t)
            .where(
                t.project_id == project_id,
                t.workflow_id.is_(None),
                t.stage_type == stage_type,
            )
            .values(workflow_id=workflow.id, stage_id=stage.id)
        )
    await session.execute(
        update(t)
        .where(t.project_id == project_id, t.workflow_id.is_(None))
        .values(
            workflow_id=workflow.id,
            stage_id=fallback.id,
            stage_type=fallback.stage_type,
        )
    )


@dataclass
class Placement:
    workflow_id: UUID
    stage_id: UUID
    stage_type: str


async def place_task(
    session: DBAsyncScopedSession,
    project: ews_models.Project,
    *,
    workflow_id: Optional[str] = None,
    stage_id: Optional[str] = None,
    stage_type: Optional[str] = None,
    current_workflow_id: Optional[UUID] = None,
) -> Placement:
    """Resolve a task's workflow + stage: an explicit stage, else the first stage of
    the target workflow with ``stage_type``, else the workflow's default stage."""
    workflows = await ensure_workflows(session, project)
    by_id = {w.id: w for w in workflows}
    target_id = to_uuid(workflow_id) or current_workflow_id
    stage_uuid = to_uuid(stage_id)
    stages_by_wf = await load_stages(session, list(by_id))
    if stage_uuid is not None:
        for wid, stages in stages_by_wf.items():
            stage = next((s for s in stages if s.id == stage_uuid), None)
            if stage is not None:
                if target_id is not None and wid != target_id and workflow_id:
                    raise ClientException(
                        detail='The stage does not belong to the given workflow.'
                    )
                return Placement(wid, stage.id, stage.stage_type)
        raise ClientException(detail=f"Unknown stage '{stage_id}' for this project.")
    if target_id is None or target_id not in by_id:
        if workflow_id:
            raise ClientException(
                detail=f"Unknown workflow '{workflow_id}' for this project."
            )
        target_id = workflows[0].id  # the default workflow comes first
    stages = stages_by_wf.get(target_id) or []
    stage = stage_for_type(stages, stage_type) or default_stage(stages)
    if stage is None:
        raise ClientException(detail='The workflow has no stages.')
    return Placement(target_id, stage.id, stage.stage_type)


async def get_workflow(
    session: DBAsyncScopedSession, project: ews_models.Project, workflow_id: str
) -> ews_models.Workflow:
    await ensure_workflows(session, project)
    workflow = await session.get(ews_models.Workflow, to_uuid(workflow_id))
    if workflow is None or workflow.project_id != project.id:
        raise NotFoundException(
            detail=f'Workflow {workflow_id} not found in this project.'
        )
    return workflow


async def get_project(
    session: DBAsyncScopedSession, project_id: str
) -> ews_models.Project:
    project = await session.get(ews_models.Project, to_uuid(project_id))
    if project is None:
        raise NotFoundException(detail=f'Project {project_id} not found.')
    return project


async def set_default_workflow(
    session: DBAsyncScopedSession, project_id: UUID, workflow_id: UUID
) -> None:
    wf = ews_models.Workflow
    await session.execute(
        update(wf)
        .where(wf.project_id == project_id)
        .values(is_default=(wf.id == workflow_id))
    )


async def set_default_stage(
    session: DBAsyncScopedSession, workflow_id: UUID, stage_id: UUID
) -> None:
    st = ews_models.WorkflowStage
    await session.execute(
        update(st)
        .where(st.workflow_id == workflow_id)
        .values(is_default=(st.id == stage_id))
    )


async def set_assignments(
    session: DBAsyncScopedSession, workflow: ews_models.Workflow, user_ids: list[str]
) -> None:
    """Replace the users assigned to a workflow (order = priority)."""
    a = ews_models.ProjectWorkflowAssignment
    existing = await session.scalars(select(a).where(a.workflow_id == workflow.id))
    for row in existing.all():
        await session.delete(row)
    clean = list(dict.fromkeys(u.strip() for u in user_ids if u and u.strip()))
    session.add_all(
        a(
            project_id=workflow.project_id,
            workflow_id=workflow.id,
            user_id=user,
            priority=(i + 1) * 10,
            assigned_at=now(),
            status=SimpleStatus.ACTIVE,
        )
        for i, user in enumerate(clean)
    )
    await session.flush()


async def move_tasks_to_workflow(
    session: DBAsyncScopedSession,
    source: ews_models.Workflow,
    target: ews_models.Workflow,
) -> None:
    """Move every task of ``source`` into ``target`` keeping stage types when possible."""
    stages = (await load_stages(session, [target.id]))[target.id]
    fallback = default_stage(stages)
    if fallback is None:
        raise ClientException(detail='The target workflow has no stages.')
    t = ews_models.Task
    by_type: dict[str, ews_models.WorkflowStage] = {}
    for s in stages:
        by_type.setdefault(s.stage_type, s)
    for stage_type, stage in by_type.items():
        await session.execute(
            update(t)
            .where(t.workflow_id == source.id, t.stage_type == stage_type)
            .values(workflow_id=target.id, stage_id=stage.id)
        )
    await session.execute(
        update(t)
        .where(t.workflow_id == source.id)
        .values(
            workflow_id=target.id, stage_id=fallback.id, stage_type=fallback.stage_type
        )
    )


def checked_work_item_types(
    process: ProjectProcess, items: list[dict[str, Any]], project: ews_models.Project
) -> list[dict[str, Any]]:
    """Validate a new work item type list: with a template, a subset of its types
    (terms may be renamed, icons / colours kept); without one, any unique keys."""
    clean: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        key = (item.get('key') or '').strip()
        term = (item.get('term') or '').strip()
        if not key or not term:
            raise ClientException(detail='Every work item type needs a key and a term.')
        if key in seen:
            raise ClientException(detail=f"Duplicate work item type '{key}'.")
        seen.add(key)
        clean.append(
            {
                k: v
                for k, v in {**item, 'key': key, 'term': term}.items()
                if v is not None
            }
        )
    if not clean:
        raise ClientException(detail='A project needs at least one work item type.')
    if process.work_item_types_locked:
        template = catalog.get_template(process.template_id) or {'work_item_types': []}
        allowed = {w['key']: w for w in template['work_item_types']}
        unknown = [w['key'] for w in clean if w['key'] not in allowed]
        if unknown:
            raise ClientException(
                detail=f'Not part of the workflow template: {", ".join(unknown)}.'
            )
        clean = [{**allowed[w['key']], 'term': w['term']} for w in clean]
    return clean
