"""Workflow HTTP controllers (EWS PPM).

- ``/api/v1/workflow-templates``: the template catalog by category (localized, ``?locale=``).
- ``/api/v1/workflow-stage-types``: canonical stage types and their lifecycle band.
- ``/api/v1/projects/{id}/workflows``: a project's workflows (boards) and their
  stages — rules in ``ews.ppm._workflow_service``.
"""

from __future__ import annotations

from typing import Optional

import db.models.ews as ews_models
from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException, NotFoundException
from foundation.http import BaseController, delete, get, patch, post, put, status
from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select, update

from .. import _workflow_service as wfs
from .. import workflow_catalog as catalog
from ..schemas._workflow_api import (
    StageTypeResponse,
    TemplateCategoryResponse,
    TemplateDetail,
    WorkflowCreateRequest,
    WorkflowResponse,
    WorkflowStageCreateRequest,
    WorkflowStageOrderRequest,
    WorkflowStageResponse,
    WorkflowStageUpdateRequest,
    WorkflowUpdateRequest,
)
from ._project_api import _touch_project

_STAGE_CLEARABLE = frozenset({'wip_limit', 'description', 'color'})


def _stage_to_response(
    s: ews_models.WorkflowStage, counts: dict
) -> WorkflowStageResponse:
    info = catalog.stage_type_info(s.stage_type)
    return WorkflowStageResponse(
        id=str(s.id),
        workflow_id=str(s.workflow_id),
        name=s.name,
        description=s.description,
        stage_type=s.stage_type,
        band=info.band if info else None,
        color=s.color,
        wip_limit=s.wip_limit,
        is_default=bool(s.is_default),
        display_order=s.display_order or 0,
        task_count=counts.get(s.id, 0),
    )


async def _workflows_response(
    session: DBAsyncScopedSession,
    project: ews_models.Project,
    workflows: list[ews_models.Workflow],
    user_id: Optional[str] = None,
) -> list[WorkflowResponse]:
    ids = [w.id for w in workflows]
    stages = await wfs.load_stages(session, ids)
    assigned = await wfs.load_assignments(session, ids)
    counts = await wfs.stage_task_counts(session, ids)
    out = []
    for w in workflows:
        if not wfs.visible_to(w, assigned.get(w.id, []), user_id, project):
            continue
        rows = [_stage_to_response(s, counts) for s in stages.get(w.id, [])]
        out.append(
            WorkflowResponse(
                id=str(w.id),
                project_id=str(w.project_id),
                name=w.name,
                description=w.description,
                workflow_type=w.workflow_type,
                is_default=bool(w.is_default),
                privacy=wfs.normalize_privacy(w.privacy),
                assigned_user_ids=assigned.get(w.id, []),
                template_id=w.template_id,
                display_order=w.display_order or 0,
                task_count=sum(r.task_count for r in rows),
                stages=rows,
                created_at=getattr(w, 'created_at', None),
            )
        )
    return out


async def _one(
    session: DBAsyncScopedSession,
    project: ews_models.Project,
    workflow: ews_models.Workflow,
) -> WorkflowResponse:
    return (await _workflows_response(session, project, [workflow]))[0]


class WorkflowTemplateController(BaseController):
    """The workflow template catalog (read-only)."""

    api_prefix = '/api/v1/workflow-templates'
    tags = ('Workflows',)

    @get('/')
    async def list_workflow_templates(
        self, locale: Optional[str] = None
    ) -> list[TemplateCategoryResponse]:
        """Categories in UI order, each with its template summaries."""
        return [TemplateCategoryResponse(**c) for c in catalog.list_categories(locale)]

    @get('/{template_id}')
    async def get_workflow_template(
        self, template_id: str, locale: Optional[str] = None
    ) -> TemplateDetail:
        template = catalog.get_template(template_id, locale)
        if template is None:
            raise NotFoundException(
                detail=f'Workflow template {template_id} not found.'
            )
        return TemplateDetail(
            **catalog.template_summary(template),
            work_item_types=template['work_item_types'],
            allowed_stage_types=template['allowed_stage_types'],
            stages=template['stages'],
            stage_suggestions=template['stage_suggestions'],
        )


class WorkflowStageTypeController(BaseController):
    """Canonical stage types (lifecycle bands drive progress analytics)."""

    api_prefix = '/api/v1/workflow-stage-types'
    tags = ('Workflows',)

    @get('/')
    async def list_workflow_stage_types(self) -> list[StageTypeResponse]:
        return [
            StageTypeResponse(
                key=s.key,
                band=s.band,
                order=s.order,
                tone=s.tone,
                excluded_from_progress=s.excluded_from_progress,
            )
            for s in catalog.stage_types()
        ]


class ProjectWorkflowController(BaseController):
    """A project's workflows and their stages."""

    api_prefix = '/api/v1/projects'
    tags = ('Workflows',)

    @get('/{project_id}/workflows')
    @db_context_session(auto_commit=True)
    async def list_project_workflows(
        self,
        project_id: str,
        session: DBAsyncScopedSession,
        user_id: Optional[str] = None,
    ) -> list[WorkflowResponse]:
        """The default workflow first; ``user_id`` hides ``assigned`` workflows the user is not on."""
        project = await wfs.get_project(session, project_id)
        workflows = await wfs.ensure_workflows(session, project)
        return await _workflows_response(session, project, workflows, user_id)

    @post('/{project_id}/workflows', status_code=status.HTTP_201_CREATED)
    @db_context_session(auto_commit=True)
    async def create_project_workflow(
        self,
        project_id: str,
        data: WorkflowCreateRequest,
        session: DBAsyncScopedSession,
    ) -> WorkflowResponse:
        project = await wfs.get_project(session, project_id)
        workflows = await wfs.ensure_workflows(session, project)
        process = wfs.ProjectProcess.of(project)
        if data.copy_from_workflow_id:
            source = await wfs.get_workflow(
                session, project, data.copy_from_workflow_id
            )
            source_stages = (await wfs.load_stages(session, [source.id]))[source.id]
            specs = [
                {
                    'name': s.name,
                    'stage_type': s.stage_type,
                    'color': s.color,
                    'wip_limit': s.wip_limit,
                    'is_default': s.is_default,
                    'description': s.description,
                }
                for s in source_stages
            ]
            workflow_type = source.workflow_type or 'kanban'
        else:
            seed = wfs.seed_process(process.template_id, None)
            specs, workflow_type = seed.stages, seed.workflow_type
        workflow, _ = await wfs.create_workflow(
            session,
            project,
            name=data.name,
            description=data.description,
            stages=specs,
            workflow_type=workflow_type,
            privacy=data.privacy or wfs.PRIVACY_ALL,
            template_id=process.template_id,
        )
        if data.assigned_user_ids:
            await wfs.set_assignments(session, workflow, data.assigned_user_ids)
        if data.is_default or not workflows:
            await wfs.set_default_workflow(session, project.id, workflow.id)
            await session.refresh(workflow)
        return await _one(session, project, workflow)

    @patch('/{project_id}/workflows/{workflow_id}')
    @db_context_session(auto_commit=True)
    async def update_project_workflow(
        self,
        project_id: str,
        workflow_id: str,
        data: WorkflowUpdateRequest,
        session: DBAsyncScopedSession,
    ) -> WorkflowResponse:
        project = await wfs.get_project(session, project_id)
        workflow = await wfs.get_workflow(session, project, workflow_id)
        if data.name is not None:
            if not data.name.strip():
                raise ClientException(detail='A workflow needs a name.')
            workflow.name = data.name.strip()
        if data.description is not None:
            workflow.description = data.description
        if data.privacy is not None:
            if data.privacy not in wfs.PRIVACIES:
                raise ClientException(detail=f"Unknown privacy '{data.privacy}'.")
            workflow.privacy = data.privacy
        if data.assigned_user_ids is not None:
            await wfs.set_assignments(session, workflow, data.assigned_user_ids)
        if data.is_default:
            await wfs.set_default_workflow(session, project.id, workflow.id)
        await session.flush()
        await session.refresh(workflow)
        return await _one(session, project, workflow)

    @delete(
        '/{project_id}/workflows/{workflow_id}', status_code=status.HTTP_204_NO_CONTENT
    )
    @db_context_session(auto_commit=True)
    async def delete_project_workflow(
        self, project_id: str, workflow_id: str, session: DBAsyncScopedSession
    ) -> None:
        """Delete a workflow; its tasks move to the default workflow (same stage type when possible)."""
        project = await wfs.get_project(session, project_id)
        workflow = await wfs.get_workflow(session, project, workflow_id)
        if workflow.is_default:
            raise ClientException(
                detail='The default workflow cannot be deleted — make another one the default first.'
            )
        default = next(
            w for w in await wfs.load_workflows(session, project.id) if w.is_default
        )
        await wfs.move_tasks_to_workflow(session, workflow, default)
        await session.execute(
            sql_delete(ews_models.ProjectWorkflowAssignment).where(
                ews_models.ProjectWorkflowAssignment.workflow_id == workflow.id
            )
        )
        await session.execute(
            sql_delete(ews_models.WorkflowStage).where(
                ews_models.WorkflowStage.workflow_id == workflow.id
            )
        )
        await session.delete(workflow)
        await _touch_project(session, project.id)

    # ── Stages ────────────────────────────────────────────────────────────────

    @post(
        '/{project_id}/workflows/{workflow_id}/stages',
        status_code=status.HTTP_201_CREATED,
    )
    @db_context_session(auto_commit=True)
    async def create_workflow_stage(
        self,
        project_id: str,
        workflow_id: str,
        data: WorkflowStageCreateRequest,
        session: DBAsyncScopedSession,
    ) -> WorkflowResponse:
        project = await wfs.get_project(session, project_id)
        workflow = await wfs.get_workflow(session, project, workflow_id)
        wfs.ProjectProcess.of(project).check_stage_type(data.stage_type)
        if not data.name.strip():
            raise ClientException(detail='A stage needs a name.')
        stages = (await wfs.load_stages(session, [workflow.id]))[workflow.id]
        position = (
            len(stages)
            if data.position is None
            else max(0, min(data.position, len(stages)))
        )
        stage = wfs.new_stage(
            workflow,
            {
                'name': data.name.strip(),
                'stage_type': data.stage_type,
                'description': data.description,
                'color': data.color,
                'wip_limit': data.wip_limit,
                'is_default': False,
            },
            position,
        )
        session.add(stage)
        await session.flush()
        ordered = [*stages[:position], stage, *stages[position:]]
        for i, s in enumerate(ordered):
            s.display_order = s.position = i
        if data.is_default:
            await wfs.set_default_stage(session, workflow.id, stage.id)
        await session.flush()
        return await _one(session, project, workflow)

    @patch('/{project_id}/workflows/{workflow_id}/stages/{stage_id}')
    @db_context_session(auto_commit=True)
    async def update_workflow_stage(
        self,
        project_id: str,
        workflow_id: str,
        stage_id: str,
        data: WorkflowStageUpdateRequest,
        session: DBAsyncScopedSession,
    ) -> WorkflowResponse:
        project = await wfs.get_project(session, project_id)
        workflow = await wfs.get_workflow(session, project, workflow_id)
        stage = await self._stage(session, workflow, stage_id)
        if data.name is not None:
            if not data.name.strip():
                raise ClientException(detail='A stage needs a name.')
            stage.name = data.name.strip()
        if data.stage_type is not None and data.stage_type != stage.stage_type:
            wfs.ProjectProcess.of(project).check_stage_type(data.stage_type)
            stage.stage_type = data.stage_type
            # Tasks mirror their stage's type (analytics).
            await session.execute(
                update(ews_models.Task)
                .where(ews_models.Task.stage_id == stage.id)
                .values(stage_type=data.stage_type)
            )
        if data.description is not None:
            stage.description = data.description
        if data.color is not None:
            stage.color = data.color
        if data.wip_limit is not None:
            stage.wip_limit = max(0, data.wip_limit) or None
        for field in set(data.clear or []) & _STAGE_CLEARABLE:
            setattr(stage, field, None)
        if data.is_default:
            await wfs.set_default_stage(session, workflow.id, stage.id)
        await session.flush()
        await session.refresh(stage)
        return await _one(session, project, workflow)

    @delete('/{project_id}/workflows/{workflow_id}/stages/{stage_id}')
    @db_context_session(auto_commit=True)
    async def delete_workflow_stage(
        self,
        project_id: str,
        workflow_id: str,
        stage_id: str,
        session: DBAsyncScopedSession,
        move_to: Optional[str] = None,
    ) -> WorkflowResponse:
        """Delete a stage; its tasks move to ``move_to`` (required when it has tasks)."""
        project = await wfs.get_project(session, project_id)
        workflow = await wfs.get_workflow(session, project, workflow_id)
        stage = await self._stage(session, workflow, stage_id)
        stages = (await wfs.load_stages(session, [workflow.id]))[workflow.id]
        if len(stages) <= 1:
            raise ClientException(detail='A workflow needs at least one stage.')
        task_count = await session.scalar(
            select(func.count(ews_models.Task.id)).where(
                ews_models.Task.stage_id == stage.id
            )
        )
        if task_count:
            if not move_to:
                raise ClientException(
                    detail=f'The stage has {task_count} task(s) — choose a stage to move them to.'
                )
            target = await self._stage(session, workflow, move_to)
            if target.id == stage.id:
                raise ClientException(
                    detail='Choose another stage to move the tasks to.'
                )
            await session.execute(
                update(ews_models.Task)
                .where(ews_models.Task.stage_id == stage.id)
                .values(stage_id=target.id, stage_type=target.stage_type)
            )
        remaining = [s for s in stages if s.id != stage.id]
        if stage.is_default:
            remaining[0].is_default = True
        for i, s in enumerate(remaining):
            s.display_order = s.position = i
        await session.delete(stage)
        await session.flush()
        await _touch_project(session, project.id)
        return await _one(session, project, workflow)

    @put('/{project_id}/workflows/{workflow_id}/stages/order')
    @db_context_session(auto_commit=True)
    async def order_workflow_stages(
        self,
        project_id: str,
        workflow_id: str,
        data: WorkflowStageOrderRequest,
        session: DBAsyncScopedSession,
    ) -> WorkflowResponse:
        """Reorder the stages (``stage_ids`` = every stage id of the workflow, in the new order)."""
        project = await wfs.get_project(session, project_id)
        workflow = await wfs.get_workflow(session, project, workflow_id)
        stages = (await wfs.load_stages(session, [workflow.id]))[workflow.id]
        by_id = {str(s.id): s for s in stages}
        if sorted(data.stage_ids) != sorted(by_id):
            raise ClientException(
                detail='stage_ids must list every stage of the workflow exactly once.'
            )
        for i, sid in enumerate(data.stage_ids):
            by_id[sid].display_order = by_id[sid].position = i
        await session.flush()
        return await _one(session, project, workflow)

    @staticmethod
    async def _stage(
        session: DBAsyncScopedSession, workflow: ews_models.Workflow, stage_id: str
    ) -> ews_models.WorkflowStage:
        stage = await session.get(ews_models.WorkflowStage, wfs.to_uuid(stage_id))
        if stage is None or stage.workflow_id != workflow.id:
            raise NotFoundException(
                detail=f'Stage {stage_id} not found in this workflow.'
            )
        return stage
