"""Work model V2 routes (taas-specs/ppm/work-model/work-model-spec.md §7): item behaviours and the item type library,
custom fields + bindings, checklist templates, approvals + policies, project templates (save as template, create from
template, duplicate). Rules live in the ``ews.ppm._*`` modules; capabilities (Ppm-0009) are enforced here."""

from __future__ import annotations

from typing import Any, Optional

import db.models.ews as ews_models
from db.models.ppm import PpmApproval, PpmApprovalPolicy
from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import NotFoundException
from foundation.http import BaseController, delete, get, patch, post, put, status
from sqlalchemy import or_, select

from ews.security import RequestScope, current_scope

from .. import _access as access
from .. import _approvals as approvals
from .. import _behaviours as behaviours
from .. import _checklist_templates as checklist_templates
from .. import _custom_fields as custom_fields
from .. import _item_types as item_types
from .. import _settings
from .. import _templates as templates
from ..schemas._work_model_api import (
    PpmApplyChecklistTemplateIn,
    PpmApprovalApproverOut,
    PpmApprovalCommentIn,
    PpmApprovalDecisionIn,
    PpmApprovalDelegateIn,
    PpmApprovalEventOut,
    PpmApprovalOut,
    PpmApprovalPolicyIo,
    PpmApprovalRequestIn,
    PpmApprovalStepIn,
    PpmApproverSpec,
    PpmBehaviourOut,
    PpmChecklistTemplateIn,
    PpmChecklistTemplateItemIo,
    PpmChecklistTemplateOut,
    PpmCreatedProjectOut,
    PpmCustomFieldIn,
    PpmCustomFieldOut,
    PpmDuplicateIn,
    PpmFieldBindingIo,
    PpmFieldBindingsIn,
    PpmInstantiateIn,
    PpmItemTypeIn,
    PpmItemTypeOut,
    PpmProjectFieldsOut,
    PpmProjectTemplateOut,
    PpmSaveAsTemplateIn,
    PpmSaveChecklistTemplateIn,
    PpmTemplateRoleOut,
)


def _type_out(row: Any, used: int | None = None) -> PpmItemTypeOut:
    return PpmItemTypeOut(**item_types.to_out(row, used))


def _field_out(row: Any) -> PpmCustomFieldOut:
    return PpmCustomFieldOut(**custom_fields.field_out(row))


def _binding_out(row: Any) -> PpmFieldBindingIo:
    return PpmFieldBindingIo(**custom_fields.binding_out(row))


def _bindings_in(items: list[PpmFieldBindingIo]) -> list[custom_fields.BindingIn]:
    return [
        custom_fields.BindingIn(
            field_id=b.field_id,
            item_type_key=b.item_type_key,
            required=b.required,
            default_value=b.default_value,
            section=b.section,
            on_create_form=b.on_create_form,
            on_card=b.on_card,
        )
        for b in items
    ]


# --- item types ----------------------------------------------------------------------------------------


class PpmItemTypeController(BaseController):
    api_prefix = '/api/v1/ppm'
    tags = ('PPM item types',)

    @get('/item-behaviours', summary='Behaviour catalog of item types (§5.1)')
    async def behaviours(self) -> list[PpmBehaviourOut]:
        return [
            PpmBehaviourOut(
                key=b.key,
                in_progress=b.in_progress,
                single_date=b.single_date,
                no_effort=b.no_effort,
                done_by_approval=b.done_by_approval,
            )
            for b in behaviours.BEHAVIOURS
        ]

    @get(
        '/item-types',
        summary="The organization's item type library (seeded from the catalog on first use)",
    )
    @db_context_session(auto_commit=True)
    async def list_types(
        self, session: DBAsyncScopedSession, include_archived: bool = False
    ) -> list[PpmItemTypeOut]:
        scope = await current_scope()
        rows = await item_types.library(
            session,
            scope.tenant_id,
            scope.organization_id,
            include_archived=include_archived,
        )
        return [_type_out(r) for r in rows]

    @post(
        '/item-types',
        status_code=status.HTTP_201_CREATED,
        summary='Create a custom item type',
    )
    @db_context_session(auto_commit=True)
    async def create_type(
        self, data: PpmItemTypeIn, session: DBAsyncScopedSession
    ) -> PpmItemTypeOut:
        scope = await current_scope()
        await _settings.require_capability(session, scope, 'item_types')
        return _type_out(await item_types.create(session, scope, data.as_dict()))

    @patch(
        '/item-types/{item_type_id}',
        summary='Change an item type (409 in_use: behaviour of a used type)',
    )
    @db_context_session(auto_commit=True)
    async def update_type(
        self, item_type_id: str, data: PpmItemTypeIn, session: DBAsyncScopedSession
    ) -> PpmItemTypeOut:
        scope = await current_scope()
        await _settings.require_capability(session, scope, 'item_types')
        row = await item_types.get(session, scope, item_type_id)
        return _type_out(await item_types.update(session, scope, row, data.as_dict()))

    @post(
        '/item-types/{item_type_id}/archive',
        summary='Archive an item type (its items keep working)',
    )
    @db_context_session(auto_commit=True)
    async def archive_type(
        self, item_type_id: str, session: DBAsyncScopedSession
    ) -> PpmItemTypeOut:
        scope = await current_scope()
        row = await item_types.get(session, scope, item_type_id)
        return _type_out(await item_types.set_archived(session, scope, row, True))

    @post('/item-types/{item_type_id}/restore', summary='Restore an archived item type')
    @db_context_session(auto_commit=True)
    async def restore_type(
        self, item_type_id: str, session: DBAsyncScopedSession
    ) -> PpmItemTypeOut:
        scope = await current_scope()
        row = await item_types.get(session, scope, item_type_id)
        return _type_out(await item_types.set_archived(session, scope, row, False))

    @get(
        '/item-types/{item_type_id}/fields',
        summary='Fields bound to the type in every project',
    )
    @db_context_session
    async def type_fields(
        self, item_type_id: str, session: DBAsyncScopedSession
    ) -> list[PpmFieldBindingIo]:
        scope = await current_scope()
        row = await item_types.get(session, scope, item_type_id)
        return [
            _binding_out(b)
            for b in await custom_fields.bindings_of(session, scope.organization_id)
            if b.project_id is None and b.item_type_key == row.key
        ]

    @put(
        '/item-types/{item_type_id}/fields',
        summary='Replace the fields bound to the type in every project',
    )
    @db_context_session(auto_commit=True)
    async def set_type_fields(
        self, item_type_id: str, data: PpmFieldBindingsIn, session: DBAsyncScopedSession
    ) -> list[PpmFieldBindingIo]:
        scope = await current_scope()
        await _settings.require_capability(session, scope, 'custom_fields')
        row = await item_types.get(session, scope, item_type_id)
        rows = await custom_fields.replace_bindings(
            session,
            scope,
            project_id=None,
            item_type_key=row.key,
            items=_bindings_in(data.bindings),
        )
        return [_binding_out(b) for b in rows]


# --- custom fields ------------------------------------------------------------------------------------


class PpmCustomFieldController(BaseController):
    api_prefix = '/api/v1/ppm/custom-fields'
    tags = ('PPM custom fields',)

    @get('/', summary="Organization fields (+ a project's own with project_id)")
    @db_context_session
    async def list_fields(
        self,
        session: DBAsyncScopedSession,
        project_id: Optional[str] = None,
        include_archived: bool = False,
    ) -> list[PpmCustomFieldOut]:
        scope = await current_scope()
        pid = None
        if project_id:
            pid = (await access.load_project(session, scope, project_id)).id
        rows = await custom_fields.definitions(
            session, scope.organization_id, pid, include_archived=include_archived
        )
        return [_field_out(r) for r in rows]

    @post(
        '/',
        status_code=status.HTTP_201_CREATED,
        summary='Create a field (organization, or a project with project_id)',
    )
    @db_context_session(auto_commit=True)
    async def create_field(
        self, data: PpmCustomFieldIn, session: DBAsyncScopedSession
    ) -> PpmCustomFieldOut:
        scope = await current_scope()
        await _settings.require_capability(session, scope, 'custom_fields')
        pid = (
            (await access.load_project(session, scope, data.project_id)).id
            if data.project_id
            else None
        )
        row = await custom_fields.create(
            session,
            scope,
            label=data.label or '',
            type_=data.type or '',
            config=data.config,
            description=data.description,
            project_id=pid,
        )
        return _field_out(row)

    @patch(
        '/{field_id}',
        summary='Rename, describe, change options / config (never the type)',
    )
    @db_context_session(auto_commit=True)
    async def update_field(
        self, field_id: str, data: PpmCustomFieldIn, session: DBAsyncScopedSession
    ) -> PpmCustomFieldOut:
        scope = await current_scope()
        row = await custom_fields.get(session, scope, field_id)
        return _field_out(
            await custom_fields.update(session, scope, row, data.as_dict())
        )

    @post('/{field_id}/archive', summary='Archive a field (values kept)')
    @db_context_session(auto_commit=True)
    async def archive_field(
        self, field_id: str, session: DBAsyncScopedSession
    ) -> PpmCustomFieldOut:
        scope = await current_scope()
        row = await custom_fields.get(session, scope, field_id)
        return _field_out(await custom_fields.set_archived(session, scope, row, True))

    @post('/{field_id}/restore', summary='Restore an archived field')
    @db_context_session(auto_commit=True)
    async def restore_field(
        self, field_id: str, session: DBAsyncScopedSession
    ) -> PpmCustomFieldOut:
        scope = await current_scope()
        row = await custom_fields.get(session, scope, field_id)
        return _field_out(await custom_fields.set_archived(session, scope, row, False))


async def _project_fields_out(
    session: DBAsyncScopedSession, scope: RequestScope, project: ews_models.Project
) -> PpmProjectFieldsOut:
    rows = await custom_fields.definitions(session, scope.organization_id, project.id)
    bindings = await custom_fields.bindings_of(
        session, scope.organization_id, project.id
    )
    return PpmProjectFieldsOut(
        fields=[_field_out(r) for r in rows],
        bindings=[_binding_out(b) for b in bindings],
    )


class ProjectFieldsController(BaseController):
    api_prefix = '/api/v1/projects'
    tags = ('PPM custom fields',)

    @get(
        '/{project_id}/fields',
        summary='Fields usable in the project and every binding that applies to it',
    )
    @db_context_session
    async def project_fields(
        self, project_id: str, session: DBAsyncScopedSession
    ) -> PpmProjectFieldsOut:
        scope = await current_scope()
        return await _project_fields_out(
            session, scope, await access.load_project(session, scope, project_id)
        )

    @put(
        '/{project_id}/fields',
        summary="Replace the project's bindings (per item type, or every item)",
    )
    @db_context_session(auto_commit=True)
    async def set_project_fields(
        self, project_id: str, data: PpmFieldBindingsIn, session: DBAsyncScopedSession
    ) -> PpmProjectFieldsOut:
        scope = await current_scope()
        await _settings.require_capability(session, scope, 'custom_fields')
        project = await access.load_project(session, scope, project_id)
        await custom_fields.replace_bindings(
            session,
            scope,
            project_id=project.id,
            item_type_key=None,
            items=_bindings_in(data.bindings),
        )
        return await _project_fields_out(session, scope, project)


# --- checklist templates ----------------------------------------------------------------------------------


def _template_out(row: Any) -> PpmChecklistTemplateOut:
    data = checklist_templates.to_out(row)
    return PpmChecklistTemplateOut(
        id=data['id'],
        name=data['name'],
        description=data['description'],
        project_id=data['project_id'],
        items=[PpmChecklistTemplateItemIo(**i) for i in data['items']],
    )


class PpmChecklistTemplateController(BaseController):
    api_prefix = '/api/v1/ppm/checklist-templates'
    tags = ('PPM checklist templates',)

    @get('/', summary="Organization templates (+ a project's own with project_id)")
    @db_context_session
    async def list_templates(
        self, session: DBAsyncScopedSession, project_id: Optional[str] = None
    ) -> list[PpmChecklistTemplateOut]:
        scope = await current_scope()
        pid = (
            (await access.load_project(session, scope, project_id)).id
            if project_id
            else None
        )
        return [
            _template_out(r)
            for r in await checklist_templates.listing(session, scope, pid)
        ]

    @post(
        '/', status_code=status.HTTP_201_CREATED, summary='Create a checklist template'
    )
    @db_context_session(auto_commit=True)
    async def create_template(
        self, data: PpmChecklistTemplateIn, session: DBAsyncScopedSession
    ) -> PpmChecklistTemplateOut:
        scope = await current_scope()
        pid = (
            (await access.load_project(session, scope, data.project_id)).id
            if data.project_id
            else None
        )
        row = await checklist_templates.create(
            session,
            scope,
            name=data.name or '',
            description=data.description,
            project_id=pid,
            items=[i.as_dict() for i in data.items or []],
        )
        return _template_out(row)

    @patch('/{template_id}', summary='Rename, describe, replace the steps')
    @db_context_session(auto_commit=True)
    async def update_template(
        self,
        template_id: str,
        data: PpmChecklistTemplateIn,
        session: DBAsyncScopedSession,
    ) -> PpmChecklistTemplateOut:
        scope = await current_scope()
        row = await checklist_templates.get(session, scope, template_id)
        payload = data.as_dict()
        if data.items is not None:
            payload['items'] = [i.as_dict() for i in data.items]
        return _template_out(
            await checklist_templates.update(session, scope, row, payload)
        )

    @delete('/{template_id}', status_code=status.HTTP_204_NO_CONTENT)
    @db_context_session(auto_commit=True)
    async def delete_template(
        self, template_id: str, session: DBAsyncScopedSession
    ) -> None:
        scope = await current_scope()
        row = await checklist_templates.get(session, scope, template_id)
        await checklist_templates.remove(session, scope, row)


class TaskChecklistTemplateController(BaseController):
    api_prefix = '/api/v1/tasks'
    tags = ('PPM checklist templates',)

    @post(
        '/{task_id}/checklist/apply-template',
        summary="Copy a template's steps into the item's checklist",
    )
    @db_context_session(auto_commit=True)
    async def apply_template(
        self,
        task_id: str,
        data: PpmApplyChecklistTemplateIn,
        session: DBAsyncScopedSession,
    ) -> dict[str, int]:
        scope = await current_scope()
        task, _ = await access.load_task(session, scope, task_id, access.TASK, 'update')
        row = await checklist_templates.get(session, scope, data.checklist_template_id)
        return {'added': await checklist_templates.apply(session, scope, task, row)}

    @post(
        '/{task_id}/checklist/save-as-template',
        status_code=status.HTTP_201_CREATED,
        summary="Save the item's checklist as a template",
    )
    @db_context_session(auto_commit=True)
    async def save_template(
        self,
        task_id: str,
        data: PpmSaveChecklistTemplateIn,
        session: DBAsyncScopedSession,
    ) -> PpmChecklistTemplateOut:
        scope = await current_scope()
        task, _ = await access.load_task(session, scope, task_id)
        row = await checklist_templates.save_from_task(
            session, scope, task, name=data.name, project_scope=data.project_scope
        )
        return _template_out(row)


# --- approvals ----------------------------------------------------------------------------------------------


async def approval_out(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    row: PpmApproval,
    *,
    detail: bool = True,
) -> PpmApprovalOut:
    rows = await approvals.approvers_of(session, row.id)
    mine = approvals.me_refs(scope)
    can_decide = row.status == 'pending' and any(
        r.user_ref in mine and r.step == row.current_step and r.decision == 'pending'
        for r in rows
    )
    current = None
    if detail and row.status == 'pending':
        try:
            subject = await approvals.subject_type(row.subject_type).load(
                session, scope, row.subject_id, 'read'
            )
            if subject.snapshot != row.subject_snapshot:
                current = subject.snapshot
        except Exception:  # noqa: BLE001 — the approver may not read the subject itself (Ppm-0873)
            current = None
    return PpmApprovalOut(
        id=str(row.id),
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        title=row.title,
        status=row.status,
        round=row.round,
        current_step=row.current_step,
        requested_by=row.requested_by,
        requested_at=row.requested_at,
        project_id=str(row.project_id) if row.project_id else None,
        note=row.note,
        due_at=row.due_at,
        decided_at=row.decided_at,
        snapshot=row.subject_snapshot or {},
        current=current,
        approvers=[
            PpmApprovalApproverOut(
                step=r.step,
                user=r.user_ref,
                rule=r.step_rule,
                decision=r.decision,
                step_name=r.step_name,
                resolved_from=r.resolved_from,
                decided_at=r.decided_at,
                comment=r.comment,
                delegated_from=r.delegated_from,
            )
            for r in rows
        ],
        events=[
            PpmApprovalEventOut(
                action=e.action,
                round=e.round,
                occurred_at=e.occurred_at,
                actor=e.actor_ref,
                step=e.step,
                comment=e.comment,
            )
            for e in await approvals.history(session, row.id)
        ]
        if detail
        else [],
        can_decide=can_decide,
        can_cancel=row.status == 'pending'
        and (row.requested_by in mine or await approvals.can_manage(scope, row)),
    )


def _steps(items: list[PpmApprovalStepIn] | None) -> list[approvals.StepIn] | None:
    if items is None:
        return None
    return [
        approvals.StepIn(
            name=s.name, rule=s.rule, approvers=[a.as_dict() for a in s.approvers]
        )
        for s in items
    ]


class PpmApprovalController(BaseController):
    api_prefix = '/api/v1/ppm/approvals'
    tags = ('PPM approvals',)

    @get(
        '/',
        summary='Approvals of a subject, of a project, or waiting for me (approver=me)',
    )
    @db_context_session
    async def list_approvals(
        self,
        session: DBAsyncScopedSession,
        subject_type: Optional[str] = None,
        subject_id: Optional[str] = None,
        status: Optional[str] = None,
        approver: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> list[PpmApprovalOut]:
        scope = await current_scope()
        if approver == 'me':
            rows = [a for a, _ in await approvals.waiting_for(session, scope)]
        elif subject_type and subject_id:
            await approvals.subject_type(subject_type).load(
                session, scope, subject_id, 'read'
            )
            rows = await approvals.for_subject(session, subject_type, subject_id)
        elif project_id:
            project = await access.load_project(session, scope, project_id)
            a = PpmApproval
            rows = list(
                (
                    await session.scalars(
                        select(a)
                        .where(a.project_id == project.id)
                        .order_by(a.requested_at.desc())
                        .limit(200)
                    )
                ).all()
            )
        else:
            a = PpmApproval
            mine = list(approvals.me_refs(scope))
            rows = list(
                (
                    await session.scalars(
                        select(a)
                        .where(
                            a.organization_id == scope.organization_id,
                            a.requested_by.in_(mine),
                        )
                        .order_by(a.requested_at.desc())
                        .limit(200)
                    )
                ).all()
            )
        if status:
            rows = [r for r in rows if r.status == status]
        return [await approval_out(session, scope, r, detail=False) for r in rows]

    @post(
        '/',
        status_code=status.HTTP_201_CREATED,
        summary='Request an approval (steps, a policy, or the matching policy)',
    )
    @db_context_session(auto_commit=True)
    async def request_approval(
        self, data: PpmApprovalRequestIn, session: DBAsyncScopedSession
    ) -> PpmApprovalOut:
        scope = await current_scope()
        await _settings.require_capability(session, scope, 'approvals')
        row = await approvals.request(
            session,
            scope,
            subject_key=data.subject_type,
            subject_id=data.subject_id,
            steps=_steps(data.steps),
            policy_id=data.policy_id,
            due_at=data.due_at,
            note=data.note,
        )
        return await approval_out(session, scope, row)

    @get('/{approval_id}', summary='Steps, approvers, history, snapshot vs current')
    @db_context_session
    async def get_approval(
        self, approval_id: str, session: DBAsyncScopedSession
    ) -> PpmApprovalOut:
        scope = await current_scope()
        return await approval_out(
            session, scope, await approvals.get(session, scope, approval_id)
        )

    @post(
        '/{approval_id}/decide',
        summary='Approve · reject · request changes (comment required for the last two)',
    )
    @db_context_session(auto_commit=True)
    async def decide(
        self,
        approval_id: str,
        data: PpmApprovalDecisionIn,
        session: DBAsyncScopedSession,
    ) -> PpmApprovalOut:
        scope = await current_scope()
        row = await approvals.get(session, scope, approval_id)
        await approvals.decide(session, scope, row, data.decision, data.comment)
        return await approval_out(session, scope, row)

    @post('/{approval_id}/delegate', summary='Hand my decision to someone else')
    @db_context_session(auto_commit=True)
    async def delegate(
        self,
        approval_id: str,
        data: PpmApprovalDelegateIn,
        session: DBAsyncScopedSession,
    ) -> PpmApprovalOut:
        scope = await current_scope()
        row = await approvals.get(session, scope, approval_id)
        await approvals.delegate(session, scope, row, data.user_id, data.comment)
        return await approval_out(session, scope, row)

    @post('/{approval_id}/cancel', summary='Cancel (requester or ppm.approval:manage)')
    @db_context_session(auto_commit=True)
    async def cancel(
        self,
        approval_id: str,
        data: PpmApprovalCommentIn,
        session: DBAsyncScopedSession,
    ) -> PpmApprovalOut:
        scope = await current_scope()
        row = await approvals.get(session, scope, approval_id)
        await approvals.cancel(session, scope, row, data.comment)
        return await approval_out(session, scope, row)

    @post('/{approval_id}/resubmit', summary='A new round after changes were requested')
    @db_context_session(auto_commit=True)
    async def resubmit(
        self,
        approval_id: str,
        data: PpmApprovalCommentIn,
        session: DBAsyncScopedSession,
    ) -> PpmApprovalOut:
        scope = await current_scope()
        row = await approvals.get(session, scope, approval_id)
        await approvals.resubmit(session, scope, row, data.comment)
        return await approval_out(session, scope, row)


def _policy_out(row: PpmApprovalPolicy) -> PpmApprovalPolicyIo:
    return PpmApprovalPolicyIo(
        id=str(row.id),
        name=row.name,
        subject_type=row.subject_type,
        project_id=str(row.project_id) if row.project_id else None,
        conditions=row.conditions or {},
        steps=[
            PpmApprovalStepIn(
                name=s.get('name'),
                rule=s.get('rule') or 'any',
                approvers=[PpmApproverSpec(**a) for a in s.get('approvers') or []],
            )
            for s in row.steps or []
        ],
        due_working_days=row.due_working_days,
        allow_self_approval=row.allow_self_approval,
        archived=row.archived_at is not None,
    )


class PpmApprovalPolicyController(BaseController):
    api_prefix = '/api/v1/ppm/approval-policies'
    tags = ('PPM approvals',)

    @get('/', summary="Organization policies (+ a project's with project_id)")
    @db_context_session
    async def list_policies(
        self, session: DBAsyncScopedSession, project_id: Optional[str] = None
    ) -> list[PpmApprovalPolicyIo]:
        scope = await current_scope()
        p = PpmApprovalPolicy
        target = p.project_id.is_(None)
        if project_id:
            pid = (await access.load_project(session, scope, project_id)).id
            target = or_(p.project_id.is_(None), p.project_id == pid)
        rows = await session.scalars(
            select(p)
            .where(p.organization_id == scope.organization_id, target)
            .order_by(p.project_id.nulls_first(), p.position)
        )
        return [_policy_out(r) for r in rows.all()]

    @post('/', status_code=status.HTTP_201_CREATED, summary='Create a policy')
    @db_context_session(auto_commit=True)
    async def create_policy(
        self, data: PpmApprovalPolicyIo, session: DBAsyncScopedSession
    ) -> PpmApprovalPolicyIo:
        scope = await current_scope()
        await _settings.require_capability(session, scope, 'approvals')
        payload = data.as_dict()
        if data.steps is not None:
            payload['steps'] = [
                s.as_dict() | {'approvers': [a.as_dict() for a in s.approvers]}
                for s in data.steps
            ]
        return _policy_out(await approvals.save_policy(session, scope, payload))

    @patch('/{policy_id}', summary='Change a policy (archived: true / false)')
    @db_context_session(auto_commit=True)
    async def update_policy(
        self, policy_id: str, data: PpmApprovalPolicyIo, session: DBAsyncScopedSession
    ) -> PpmApprovalPolicyIo:
        scope = await current_scope()
        row = await session.get(
            PpmApprovalPolicy, access.parse_uuid(policy_id, 'approval policy')
        )
        if row is None or row.organization_id != scope.organization_id:
            raise NotFoundException(detail='approval policy not found')
        payload = data.as_dict()
        if data.steps is not None:
            payload['steps'] = [
                s.as_dict() | {'approvers': [a.as_dict() for a in s.approvers]}
                for s in data.steps
            ]
        return _policy_out(await approvals.save_policy(session, scope, payload, row))


# --- project templates ---------------------------------------------------------------------------------------


def _created(project: ews_models.Project) -> PpmCreatedProjectOut:
    return PpmCreatedProjectOut(
        id=str(project.id),
        name=project.name or '',
        kind=project.kind,
        code=project.code,
    )


class PpmProjectTemplateController(BaseController):
    api_prefix = '/api/v1/ppm/project-templates'
    tags = ('PPM project templates',)

    @get(
        '/',
        summary='Template gallery (search, category; item count, milestones, working days)',
    )
    @db_context_session
    async def gallery(
        self,
        session: DBAsyncScopedSession,
        q: Optional[str] = None,
        category: Optional[str] = None,
    ) -> list[PpmProjectTemplateOut]:
        scope = await current_scope()
        out = []
        for t in await templates.gallery(session, scope, q, category):
            out.append(
                PpmProjectTemplateOut(
                    **{**t, 'roles': [PpmTemplateRoleOut(**r) for r in t['roles']]}
                )
            )
        return out

    @post(
        '/{template_id}/instantiate',
        status_code=status.HTTP_201_CREATED,
        summary='Create a project from a template',
    )
    @db_context_session(auto_commit=True)
    async def instantiate(
        self, template_id: str, data: PpmInstantiateIn, session: DBAsyncScopedSession
    ) -> PpmCreatedProjectOut:
        scope = await current_scope()
        await _settings.require_capability(session, scope, 'project_templates')
        template = await session.get(
            ews_models.Project, access.parse_uuid(template_id, 'template')
        )
        if (
            template is None
            or template.deleted_at is not None
            or template.kind != 'template'
            or template.organization_id != scope.organization_id
        ):
            raise NotFoundException(detail='template not found')
        project = await templates.instantiate(
            session,
            scope,
            template,
            name=data.name,
            code=data.code,
            start_date=data.start_date,
            role_map=data.role_map,
            include_field_values=data.include_field_values,
            include_members=data.include_members,
        )
        return _created(project)


class ProjectTemplateActionsController(BaseController):
    api_prefix = '/api/v1/projects'
    tags = ('PPM project templates',)

    @post(
        '/{project_id}/save-as-template',
        status_code=status.HTTP_201_CREATED,
        summary='Save a project as a template',
    )
    @db_context_session(auto_commit=True)
    async def save_as_template(
        self, project_id: str, data: PpmSaveAsTemplateIn, session: DBAsyncScopedSession
    ) -> PpmCreatedProjectOut:
        scope = await current_scope()
        await _settings.require_capability(session, scope, 'project_templates')
        source = await access.load_project(session, scope, project_id)
        template = await templates.save_as_template(
            session,
            scope,
            source,
            name=data.name,
            keep_people=data.keep_people,
            include_field_values=data.include_field_values,
            include_members=data.include_members,
            category=data.category,
        )
        return _created(template)

    @post(
        '/{project_id}/duplicate',
        status_code=status.HTTP_201_CREATED,
        summary='Duplicate a project (same copy engine)',
    )
    @db_context_session(auto_commit=True)
    async def duplicate(
        self, project_id: str, data: PpmDuplicateIn, session: DBAsyncScopedSession
    ) -> PpmCreatedProjectOut:
        scope = await current_scope()
        source = await access.load_project(session, scope, project_id)
        project = await templates.duplicate(
            session,
            scope,
            source,
            name=data.name,
            start_date=data.start_date,
            include_field_values=data.include_field_values,
            include_members=data.include_members,
        )
        return _created(project)
