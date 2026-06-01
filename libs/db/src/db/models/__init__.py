"""
IMPORTANT:
 - To enable migration of a model, you need to import it in this __init__.py so it registers with the metadata registry.
"""

from advanced_alchemy.base import AdvancedDeclarativeBase

# Audit Trails
from .core._audit_log import AuditLog

# Authorization
from .core._casbin_rule import CasbinRule

# IAM
from .core._email_verification_token import EmailVerificationToken
from .core._oauth_account import UserOAuthAccount
from .core._password_reset_token import PasswordResetToken
from .core._refresh_token import RefreshToken
from .core._role import Role
from .core._tag import Tag
from .core._team import Team
from .core._team_invitation import TeamInvitation
from .core._team_member import TeamMember
from .core._team_roles import TeamRoles
from .core._team_tag import team_tag
from .core._user import User
from .core._user_role import UserRole

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
