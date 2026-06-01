from enum import StrEnum


class ProjectPrivacy(StrEnum):
    """
    Enum for project privacy levels.
    """

    # GLOBAL = 'Global' # Not support for now
    """ Visible readonly to everyone in the internet """

    PUBLIC = 'public'
    """ Visible to everyone in the tenant """

    PRIVATE = 'private'
    """ Only visible to project members """

    ORGANIZATION = 'org'
    """ Only visible within the organization """


class ProjectStatus(StrEnum):
    """
    Comprehensive project status enum for cross-business area project management.

    Lifecycle Statuses:
    - NEW: Initial state when project is created
    - PLANNED: Project is planned but not yet started
    - IN_PROGRESS: Project is actively being worked on
    - ON_HOLD: Project is temporarily paused
    - COMPLETED: Project has been successfully completed
    - CANCELLED: Project was cancelled before completion
    - ARCHIVED: Project is archived (historical record)

    Risk & Performance Statuses:
    - AT_RISK: Project has identified risks that may impact delivery
    - BLOCKED: Project is blocked by dependencies or issues
    - DELAYED: Project is running behind schedule
    - AHEAD: Project is ahead of schedule

    Review & Approval Statuses:
    - PENDING_APPROVAL: Waiting for approval to proceed
    - UNDER_REVIEW: Project deliverables are being reviewed
    - APPROVED: Project has been approved
    - REJECTED: Project proposal or deliverables rejected

    Execution Statuses:
    - TESTING: Project in testing phase
    - DEPLOYMENT: Project in deployment phase
    - MAINTENANCE: Project in maintenance mode (ongoing support)
    - CLOSING: Project in closing/handover phase

    Special Statuses:
    - DRAFT: Project is in draft state (not yet submitted)
    - TEMPLATE: Project is a template for creating new projects
    - INACTIVE: Project exists but is not currently active
    """

    # Lifecycle statuses, which represent the overall stage of the project in its lifecycle
    NEW = 'New'
    DRAFT = 'Draft'
    PLANNED = 'Planned'
    IN_PROGRESS = 'In Progress'
    ON_HOLD = 'On Hold'
    COMPLETED = 'Completed'
    CANCELLED = 'Cancelled'
    ARCHIVED = 'Archived'

    # Risk & Performance statuses, which indicate potential issues or progress relative to the plan
    AT_RISK = 'At Risk'
    BLOCKED = 'Blocked'
    DELAYED = 'Delayed'
    AHEAD = 'Ahead of Schedule'

    # Review & Approval statuses, which indicate the state of any required reviews or approvals for the project
    PENDING_APPROVAL = 'Pending Approval'
    UNDER_REVIEW = 'Under Review'
    APPROVED = 'Approved'
    REJECTED = 'Rejected'

    # Execution statuses, which represent the phases of project execution
    TESTING = 'Testing'
    DEPLOYMENT = 'Deployment'
    MAINTENANCE = 'Maintenance'
    CLOSING = 'Closing'

    # Special statuses, which represent specific conditions or types of projects
    TEMPLATE = 'Template'
    INACTIVE = 'Inactive'
