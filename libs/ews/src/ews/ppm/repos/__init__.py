from __future__ import annotations

from typing import Any

import db.models.ews as ews_models
from db import BaseAsyncRepository
from foundation.db.types import DBAsyncScopedSession, DBAsyncSession

from ._category_repo import CategoryRepository
from ._checklist_template_item_repo import ChecklistTemplateItemRepository
from ._checklist_template_repo import ChecklistTemplateRepository
from ._payrate_adjustment_repo import PayrateAdjustmentRepository
from ._payrate_repo import PayrateRepository
from ._payroll_repo import PayrollRepository
from ._payrun_repo import PayrunRepository
from ._project_action_repo import ProjectActionRepository
from ._project_audit_log_repo import ProjectAuditLogRepository
from ._project_comment_repo import ProjectCommentRepository
from ._project_repo import ProjectRepository
from ._project_risk_repo import ProjectRiskRepository
from ._project_team_repo import ProjectTeamRepository
from ._project_update_repo import ProjectUpdateRepository
from ._project_user_repo import ProjectUserRepository
from ._project_workflow_assignment_repo import ProjectWorkflowAssignmentRepository
from ._project_workflow_stage_item_repo import ProjectWorkflowStageItemRepository
from ._task_checklist_item_repo import TaskChecklistItemRepository
from ._task_repo import TaskRepository
from ._task_user_repo import TaskUserRepository
from ._timelog_repo import TimelogRepository
from ._workflow_repo import WorkflowRepository
from ._workflow_stage_repo import WorkflowStageRepository

try:
    from ._project_wiki_repo import ProjectWikiRepository
except Exception:
    ProjectWikiRepository: type[BaseAsyncRepository[Any]] | None = None


type SessionLike = DBAsyncSession | DBAsyncScopedSession


ALL_REPOSITORIES = {
    'category': CategoryRepository,
    'checklist_template': ChecklistTemplateRepository,
    'checklist_template_item': ChecklistTemplateItemRepository,
    'payrate': PayrateRepository,
    'payrate_adjustment': PayrateAdjustmentRepository,
    'payroll': PayrollRepository,
    'payrun': PayrunRepository,
    'project': ProjectRepository,
    'project_action': ProjectActionRepository,
    'project_audit_log': ProjectAuditLogRepository,
    'project_comment': ProjectCommentRepository,
    'project_risk': ProjectRiskRepository,
    'project_team': ProjectTeamRepository,
    'project_update': ProjectUpdateRepository,
    'project_user': ProjectUserRepository,
    'project_workflow_assignment': ProjectWorkflowAssignmentRepository,
    'project_workflow_stage_item': ProjectWorkflowStageItemRepository,
    'task': TaskRepository,
    'task_checklist_item': TaskChecklistItemRepository,
    'task_user': TaskUserRepository,
    'timelog': TimelogRepository,
    'workflow': WorkflowRepository,
    'workflow_stage': WorkflowStageRepository,
}

if ProjectWikiRepository is not None:
    ALL_REPOSITORIES['project_wiki'] = ProjectWikiRepository


MODEL_TO_REPOSITORY = {
    ews_models.Category: CategoryRepository,
    ews_models.ChecklistTemplate: ChecklistTemplateRepository,
    ews_models.ChecklistTemplateItem: ChecklistTemplateItemRepository,
    ews_models.Payrate: PayrateRepository,
    ews_models.PayrateAdjustment: PayrateAdjustmentRepository,
    ews_models.Payroll: PayrollRepository,
    ews_models.Payrun: PayrunRepository,
    ews_models.Project: ProjectRepository,
    ews_models.ProjectAction: ProjectActionRepository,
    ews_models.ProjectAuditLog: ProjectAuditLogRepository,
    ews_models.ProjectComment: ProjectCommentRepository,
    ews_models.ProjectRisk: ProjectRiskRepository,
    ews_models.ProjectTeam: ProjectTeamRepository,
    ews_models.ProjectUpdate: ProjectUpdateRepository,
    ews_models.ProjectUser: ProjectUserRepository,
    ews_models.ProjectWorkflowAssignment: ProjectWorkflowAssignmentRepository,
    ews_models.ProjectWorkflowStageItem: ProjectWorkflowStageItemRepository,
    ews_models.Task: TaskRepository,
    ews_models.TaskChecklistItem: TaskChecklistItemRepository,
    ews_models.TaskUser: TaskUserRepository,
    ews_models.Timelog: TimelogRepository,
    ews_models.Workflow: WorkflowRepository,
    ews_models.WorkflowStage: WorkflowStageRepository,
}


class RepoFactory:
    """Factory for PPM repository classes and instances."""

    @staticmethod
    def get_repo(
        repository_type: type[BaseAsyncRepository],
        session: SessionLike,
    ) -> BaseAsyncRepository:
        return repository_type(session=session)

    @staticmethod
    def get_repo_by_name(name: str, session: SessionLike) -> BaseAsyncRepository:
        repository_type = ALL_REPOSITORIES.get(name)
        if repository_type is None:
            raise KeyError(f'No repository found for name: {name}')
        return repository_type(session=session)

    @staticmethod
    def get_repo_by_model(model_type: type, session: SessionLike) -> BaseAsyncRepository:
        repository_type = MODEL_TO_REPOSITORY.get(model_type)
        if repository_type is None:
            raise KeyError(f'No repository found for model: {model_type}')
        return repository_type(session=session)


__all__ = [
    'SessionLike',
    'RepoFactory',
    'ALL_REPOSITORIES',
    'MODEL_TO_REPOSITORY',
    'CategoryRepository',
    'ChecklistTemplateRepository',
    'ChecklistTemplateItemRepository',
    'PayrateRepository',
    'PayrateAdjustmentRepository',
    'PayrollRepository',
    'PayrunRepository',
    'ProjectRepository',
    'ProjectActionRepository',
    'ProjectAuditLogRepository',
    'ProjectCommentRepository',
    'ProjectRiskRepository',
    'ProjectTeamRepository',
    'ProjectUpdateRepository',
    'ProjectUserRepository',
    'ProjectWorkflowAssignmentRepository',
    'ProjectWorkflowStageItemRepository',
    'TaskRepository',
    'TaskChecklistItemRepository',
    'TaskUserRepository',
    'TimelogRepository',
    'WorkflowRepository',
    'WorkflowStageRepository',
]

if ProjectWikiRepository is not None:
    __all__.append('ProjectWikiRepository')
