"""
IMPORTANT:
 - To enable migration of a model, you need to import it in this __init__.py so it registers with the metadata registry.
 - The resiliant tables (outboxes, DLQ, …) are owned by ``resiliant.models``; the
   migration env imports that package too (``db/migrations/env.py``).
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
    Organization,
    OrganizationMember,
    PasswordResetToken,
    RefreshToken,
    Role,
    Tag,
    Team,
    TeamInvitation,
    TeamMember,
    Tenant,
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

# Media library (app ``media``)
from .media import MediaAsset, MediaFavorite, MediaFolder, MediaUsage

# Site builder (app ``sites``)
from .sites import (
    Site,
    SiteAiUsage,
    SiteAudit,
    SiteFormSubmission,
    SiteMenu,
    SitePage,
    SitePageRevision,
    SiteRedirect,
    SiteRelease,
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
    'Tenant',
    'Organization',
    'OrganizationMember',

    # Resiliant

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

    # Media
    'MediaAsset',
    'MediaFavorite',
    'MediaFolder',
    'MediaUsage',

    # Sites
    'Site',
    'SiteAiUsage',
    'SiteAudit',
    'SiteFormSubmission',
    'SiteMenu',
    'SitePage',
    'SitePageRevision',
    'SiteRedirect',
    'SiteRelease',

    # Banking
    'CryptoToken',
]
