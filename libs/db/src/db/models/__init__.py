"""
IMPORTANT:
 - To enable migration of a model, you need to import it in this __init__.py so it registers with the metadata registry.
"""

from advanced_alchemy.base import AdvancedDeclarativeBase

# Core models (IAM, Auth, etc.)
from .core import (
    AuditLog,
    CasbinRule,
    EmailVerificationToken,
    PasswordResetToken,
    RefreshToken,
    Role,
    Tag,
    Team,
    TeamInvitation,
    TeamMember,
    TeamRoles,
    User,
    UserOAuthAccount,
    UserRole,
    team_tag,
)

# PPM (Project / Portfolio Management)
from .ews import (
    Category,
    ChecklistTemplate,
    ChecklistTemplateItem,
    CrmAccount,
    CrmAccountAddress,
    Payrate,
    PayrateAdjustment,
    Payroll,
    Payrun,
    PpmTag,
    PpmTagMapping,
    Project,
    ProjectAction,
    ProjectComment,
    ProjectRisk,
    ProjectTeam,
    ProjectUpdate,
    ProjectUser,
    ProjectWorkflowAssignment,
    ProjectWorkflowStageItem,
    Task,
    TaskChecklistItem,
    TaskUser,
    Timelog,
    Workflow,
    WorkflowStage,
)

# from sqlalchemy.orm import DeclarativeBase

__all__ = [
    'AdvancedDeclarativeBase',
    'AuditLog',
    'EmailVerificationToken',
    'PasswordResetToken',
    'RefreshToken',
    'Role',
    'Tag',
    'Team',
    'TeamInvitation',
    'TeamMember',
    'TeamRoles',
    'User',
    'UserOAuthAccount',
    'UserRole',
    'team_tag',
    'CasbinRule',
    # CRM
    'CrmAccount',
    'CrmAccountAddress',
    # PPM
    'Category',
    'ChecklistTemplate',
    'ChecklistTemplateItem',
    'Payrate',
    'PayrateAdjustment',
    'Payroll',
    'Payrun',
    'PpmTag',
    'PpmTagMapping',
    'Project',
    'ProjectAction',
    'ProjectComment',
    'ProjectRisk',
    'ProjectTeam',
    'ProjectUpdate',
    'ProjectUser',
    'ProjectWorkflowAssignment',
    'ProjectWorkflowStageItem',
    'Task',
    'TaskChecklistItem',
    'TaskUser',
    'Timelog',
    'Workflow',
    'WorkflowStage',
]
