"""
IMPORTANT:
 - To enable migration of a model, you need to import it in this __init__.py so it registers with the metadata registry.
"""

from advanced_alchemy.base import AdvancedDeclarativeBase

from .banking import (
    CryptoToken,
)

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
from .resiliant import (
    DLQEventArchiveTable,
    DLQEventTable,
    OutboxEventArchiveTable,
    OutboxEventTable,
    ProcessedEventTable,
)

# from sqlalchemy.orm import DeclarativeBase


__all__ = [
    # Core / Iam
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
    'User',
    'UserOAuthAccount',
    'UserRole',
    'team_tag',
    'CasbinRule',

    # Resiliant
    'DLQEventTable',
    'DLQEventArchiveTable',
    'OutboxEventTable',
    'OutboxEventArchiveTable',
    'ProcessedEventTable',

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

    # Banking
    'CryptoToken',
]
