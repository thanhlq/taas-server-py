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

# Blog (app ``blog``)
from .blog import (
    Blog,
    BlogAuthor,
    BlogCategory,
    BlogPost,
    BlogPostAuthor,
    BlogPostRevision,
    BlogPostTag,
    BlogRelease,
    BlogTag,
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
    CrmContact,
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

# File Manager (app ``files``)
from .files import FileActivity, FileContent, FileDrive, FileNode, FilePreview, FileStar, FileVersion

# Knowledge Center (app ``knowledge``)
from .knowledge import KbAttachment, KbPage, KbPageRevision, KbSpace

# Platform notifications (one inbox for every app)
from .notifications import Notification, NotificationDelivery, NotificationPreference, NotificationUserSettings

# PPM tables ``taas_ppm_*`` (app ``ppm``; older PPM tables in ``ews``)
from .ppm import (
    PpmApproval,
    PpmApprovalApprover,
    PpmApprovalEvent,
    PpmApprovalPolicy,
    PpmAttachment,
    PpmAuditEvent,
    PpmAutomationRule,
    PpmAutomationRun,
    PpmCustomField,
    PpmCustomFieldBinding,
    PpmCustomFieldValue,
    PpmDashboard,
    PpmDashboardShare,
    PpmForm,
    PpmProjectContact,
    PpmFormVersion,
    PpmHealthOverride,
    PpmHealthPolicy,
    PpmHealthSnapshot,
    PpmItemType,
    PpmMention,
    PpmMyWorkPlan,
    PpmPhase,
    PpmProjectDailyStats,
    PpmRequest,
    PpmTimeCategory,
    PpmTimesheet,
    PpmSettings,
    PpmUserSettings,
    PpmWorkItemLink,
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
    'CrmContact',
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

    # Files
    'FileActivity',
    'FileContent',
    'FileDrive',
    'FileNode',
    'FilePreview',
    'FileStar',
    'FileVersion',

    # Knowledge
    'KbAttachment',
    'KbPage',
    'KbPageRevision',
    'KbSpace',

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

    # Blog
    'Blog',
    'BlogAuthor',
    'BlogCategory',
    'BlogPost',
    'BlogPostAuthor',
    'BlogPostRevision',
    'BlogPostTag',
    'BlogRelease',
    'BlogTag',

    # Banking
    'CryptoToken',
    # Notifications
    'Notification',
    'NotificationDelivery',
    'NotificationPreference',
    'NotificationUserSettings',
    # PPM (taas_ppm_*)
    'PpmApproval',
    'PpmApprovalApprover',
    'PpmApprovalEvent',
    'PpmApprovalPolicy',
    'PpmAttachment',
    'PpmAuditEvent',
    'PpmAutomationRule',
    'PpmAutomationRun',
    'PpmCustomField',
    'PpmCustomFieldBinding',
    'PpmCustomFieldValue',
    'PpmDashboard',
    'PpmDashboardShare',
    'PpmForm',
    'PpmProjectContact',
    'PpmFormVersion',
    'PpmHealthOverride',
    'PpmHealthPolicy',
    'PpmHealthSnapshot',
    'PpmItemType',
    'PpmMention',
    'PpmMyWorkPlan',
    'PpmPhase',
    'PpmProjectDailyStats',
    'PpmRequest',
    'PpmTimeCategory',
    'PpmTimesheet',
    'PpmSettings',
    'PpmUserSettings',
    'PpmWorkItemLink',
]
