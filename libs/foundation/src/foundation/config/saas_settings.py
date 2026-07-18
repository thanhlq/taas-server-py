# .venv/lib/python3.13/site-packages/litestar_email/message.py

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from foundation.utils.env_utils import get_env


@dataclass
class SaaSSettings:
    """SaaS configuration.
    """

    saas_enabled: bool = field(default_factory=get_env('SAAS_ENABLED', True, bool))
    """
    When enabled, organization is required during root account registration, and the user will be created in the organization.
    """

    email_as_username: bool = field(default_factory=get_env('EMAIL_AS_USERNAME', False, bool))
    """
    When enabled, the email address will be used as the username for the user.
    When disabled, the username will be generated from the email address (the part before the @).
    """

    FROM_EMAIL: str = field(
        default_factory=get_env('EMAIL_FROM_ADDRESS', 'noreply@localhost')
    )
    """Default from email address."""
    FROM_NAME: str = field(default_factory=get_env('EMAIL_FROM_NAME', 'Litestar App'))


    @staticmethod
    @lru_cache(maxsize=1)
    def get_settings() -> 'SaaSSettings':
        """Return SaaSSettings instance.

        Returns:
            The SaaS settings.
        """
        return SaaSSettings()
