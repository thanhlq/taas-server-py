from platform_core.utils.singleton import singleton
from dataclasses import field, dataclass
from platform_core.utils import get_env


@singleton
@dataclass
class AuthSettings:
    """Authentication settings for the IAM system."""

    email_as_username: bool = field(
        default_factory=get_env('IAM_USE_EMAIL_AS_USERNAME', True, bool)
    )

    saas_enabled: bool = field(
        default_factory=get_env('IAM_SAAS_ENABLED', False, bool)
    )
