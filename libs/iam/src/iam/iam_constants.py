from enum import StrEnum


class Roles(StrEnum):
    """Predefined user roles."""

    TENANT_ADMIN = 'tenant_admin'  # Has access to all resources within a tenant
    ORGANIZATION_ADMIN = 'organization_admin'  # In a specific organization
    USER = 'user'  # Regular user in a tenant with limited access


class IamFrontendRoutes:
    """Constants for IAM frontend routes."""

    VERIFY_ACCOUNT = '/verify-account'
    RESET_PASSWORD = '/reset-password'


class IamTemplates:
    """Constants for mail template names."""

    PASSWORD_RESET = 'password_reset.html'
    ACCOUNT_EMAIL_VERIFICATION = 'emails/account_verification.mjml'
    WELCOME_EMAIL = 'emails/account_welcome.mjml'
    USER_OTP = 'emails/user_otp.mjml'
    NOTIFICATION = 'notification.html'


# ============================================================================
# KAFKA TOPICS
# ============================================================================


class IamTopics:
    """
    IAM Kafka Topics - organized by domain and concern

    Topic Strategy:
    - Separate topics for different concerns (lifecycle, auth, authz, sync)
    - Enables independent scaling and retention policies
    - Allows different consumer groups to subscribe only to relevant events
    """

    # Core tenant management
    IAM_TENANT_CREATED = 'iam.tenant.created'

    # User lifecycle in internal database
    IAM_USER_REGISTER = 'iam.user.registered'

    # Authentication & session events from IAM provider
    IAM_AUTH = 'iam.auth'

    # Authorization (roles, groups, permissions)
    IAM_AUTHZ = 'iam.authz'

    # Sync events between internal DB and IAM provider
    IAM_SYNC = 'iam.sync'

    # MFA events
    IAM_MFA = 'iam.mfa'

    # Legacy/backward compatibility (deprecated - use specific topics above)
    IAM = 'iam'  # Keep for backward compatibility


class IamEvents(StrEnum):
    # Tenant Events
    TENANT_CREATED = 'tenant.created'
    TENANT_UPDATED = 'tenant.updated'
    TENANT_SUSPENDED = 'tenant.suspended'
    TENANT_ACTIVATED = 'tenant.activated'

    # User Lifecycle Events (Internal DB)
    USER_DIRECTORY_CREATED = 'user.directory_created'
    """ Indicates a new user has registered an account in the directory (keycloak, cognito,...). """

    USER_REGISTERED = 'user.registered'
    """ Indicates the completion of user registration process (internal data prepared). """

    USER_EMAIL_VERIFIED = 'user.email_verified'
    USER_PROFILE_UPDATED = 'user.profile_updated'
    USER_DEACTIVATED = 'user.deactivated'
    USER_REACTIVATED = 'user.reactivated'
    USER_DELETED = 'user.deleted'

    # Authentication Events (IAM Provider)
    USER_AUTHENTICATED = 'user.authenticated'
    USER_AUTHENTICATION_FAILED = 'user.authentication_failed'
    USER_LOGGED_OUT = 'user.logged_out'
    USER_PASSWORD_CHANGED = 'user.password_changed'
    USER_PASSWORD_RESET_REQUESTED = 'user.password_reset_requested'
    USER_PASSWORD_RESET_COMPLETED = 'user.password_reset_completed'

    # Session Events
    SESSION_CREATED = 'session.created'
    SESSION_EXPIRED = 'session.expired'
    SESSION_REVOKED = 'session.revoked'

    # Authorization Events
    USER_ROLE_ASSIGNED = 'user.role_assigned'
    USER_ROLE_REVOKED = 'user.role_revoked'
    USER_GROUP_ASSIGNED = 'user.group_assigned'
    USER_GROUP_REMOVED = 'user.group_removed'
    USER_PERMISSIONS_CHANGED = 'user.permissions_changed'

    # IAM Provider Sync Events
    USER_SYNCED_TO_PROVIDER = 'user.synced_to_provider'
    USER_SYNCED_FROM_PROVIDER = 'user.synced_from_provider'

    # MFA Events
    MFA_ENABLED = 'mfa.enabled'
    MFA_DISABLED = 'mfa.disabled'
    MFA_VERIFICATION_SUCCEEDED = 'mfa.verification_succeeded'
    MFA_VERIFICATION_FAILED = 'mfa.verification_failed'


# ============================================================================
# EVENT TO TOPIC MAPPING
# ============================================================================

EVENT_TOPIC_MAPPING = {
    # Tenant events
    IamEvents.TENANT_CREATED: IamTopics.IAM_TENANT_CREATED,
    IamEvents.TENANT_UPDATED: IamTopics.IAM_TENANT_CREATED,
    IamEvents.TENANT_SUSPENDED: IamTopics.IAM_TENANT_CREATED,
    IamEvents.TENANT_ACTIVATED: IamTopics.IAM_TENANT_CREATED,
    # User lifecycle events
    IamEvents.USER_DIRECTORY_CREATED: IamTopics.IAM_USER_REGISTER,
    IamEvents.USER_REGISTERED: IamTopics.IAM_USER_REGISTER,
    IamEvents.USER_EMAIL_VERIFIED: IamTopics.IAM_USER_REGISTER,
    IamEvents.USER_PROFILE_UPDATED: IamTopics.IAM_USER_REGISTER,
    IamEvents.USER_DEACTIVATED: IamTopics.IAM_USER_REGISTER,
    IamEvents.USER_REACTIVATED: IamTopics.IAM_USER_REGISTER,
    IamEvents.USER_DELETED: IamTopics.IAM_USER_REGISTER,
    # Authentication events
    IamEvents.USER_AUTHENTICATED: IamTopics.IAM_AUTH,
    IamEvents.USER_AUTHENTICATION_FAILED: IamTopics.IAM_AUTH,
    IamEvents.USER_LOGGED_OUT: IamTopics.IAM_AUTH,
    IamEvents.USER_PASSWORD_CHANGED: IamTopics.IAM_AUTH,
    IamEvents.USER_PASSWORD_RESET_REQUESTED: IamTopics.IAM_AUTH,
    IamEvents.USER_PASSWORD_RESET_COMPLETED: IamTopics.IAM_AUTH,
    IamEvents.SESSION_CREATED: IamTopics.IAM_AUTH,
    IamEvents.SESSION_EXPIRED: IamTopics.IAM_AUTH,
    IamEvents.SESSION_REVOKED: IamTopics.IAM_AUTH,
    # Authorization events
    IamEvents.USER_ROLE_ASSIGNED: IamTopics.IAM_AUTHZ,
    IamEvents.USER_ROLE_REVOKED: IamTopics.IAM_AUTHZ,
    IamEvents.USER_GROUP_ASSIGNED: IamTopics.IAM_AUTHZ,
    IamEvents.USER_GROUP_REMOVED: IamTopics.IAM_AUTHZ,
    IamEvents.USER_PERMISSIONS_CHANGED: IamTopics.IAM_AUTHZ,
    # Sync events
    IamEvents.USER_SYNCED_TO_PROVIDER: IamTopics.IAM_SYNC,
    IamEvents.USER_SYNCED_FROM_PROVIDER: IamTopics.IAM_SYNC,
    # MFA events
    IamEvents.MFA_ENABLED: IamTopics.IAM_MFA,
    IamEvents.MFA_DISABLED: IamTopics.IAM_MFA,
    IamEvents.MFA_VERIFICATION_SUCCEEDED: IamTopics.IAM_MFA,
    IamEvents.MFA_VERIFICATION_FAILED: IamTopics.IAM_MFA,
}


def get_iam_topic_for_event(event_type: IamEvents) -> str:
    """
    Get the appropriate Kafka topic for an IAM event.

    Args:
        event_type: The IAM event type

    Returns:
        The Kafka topic name for this event
    """
    return EVENT_TOPIC_MAPPING.get(event_type, IamTopics.IAM)

class IamConstants:
    """Constants for IAM module."""

    OTP_LENGTH = 6
    OTP_VALIDITY_SECONDS = 300  # 5 minutes
    OTP_SIGNUP_EMAIL_VALIDITY_SECONDS = 1800  # 30 minutes
    PASSWORD_RESET_TOKEN_EXPIRY_HOURS = 1  # 1 hour
    # EMAIL_VERIFICATION_TOKEN_EXPIRY_HOURS = 24  # 24 hours
    MAX_LOGIN_ATTEMPTS = 5
    ACCOUNT_LOCK_DURATION_MINUTES = 15  # 15 minutes
    DEFAULT_USER_ROLE = 'user'
    ADMIN_USER_ROLE = 'admin'
    SUPERADMIN_USER_ROLE = 'superadmin'
    PASSWORD_MIN_LENGTH = 8
    PASSWORD_COMPLEXITY_REGEX = (
        r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$'
    )
    SESSION_TIMEOUT_MINUTES = 30  # 30 minutes
    REFRESH_TOKEN_EXPIRY_DAYS = 30  # 30 days

    CACHE_SIGNUP_OTP_PREFIX = 'iam_signup_otp:'
    CACHE_PASSWORD_RESET_OTP_PREFIX = 'iam_password_reset_otp:'
    CACHE_EMAIL_VERIFICATION_OTP_PREFIX = 'iam_email_verification_otp:'
    CACHE_ACCOUNT_LOCK_PREFIX = 'iam_account_lock:'
    CACHE_LOGIN_ATTEMPTS_PREFIX = 'iam_login_attempts:'
    CACHE_SESSION_PREFIX = 'iam_session:'
