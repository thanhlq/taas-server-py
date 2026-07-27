from dataclasses import dataclass, field
from functools import lru_cache

from foundation.utils import get_env


@dataclass
class AuthSettings:
    """Authentication settings for the IAM system."""

    email_as_username: bool = field(
        default_factory=get_env('IAM_USE_EMAIL_AS_USERNAME', True, bool)
    )

    saas_enabled: bool = field(default_factory=get_env('IAM_SAAS_ENABLED', False, bool))


@lru_cache(maxsize=1)
def get_auth_settings() -> AuthSettings:
    return AuthSettings()


@dataclass
class PasswordPolicy:
    """Password policy settings for the IAM system."""

    min_length: int = field(default_factory=get_env('IAM_PASSWORD_MIN_LENGTH', 8, int))
    max_length: int = field(default_factory=get_env('IAM_PASSWORD_MAX_LENGTH', 64, int))
    require_uppercase: bool = field(
        default_factory=get_env('IAM_PASSWORD_REQUIRE_UPPERCASE', True, bool)
    )
    require_lowercase: bool = field(
        default_factory=get_env('IAM_PASSWORD_REQUIRE_LOWERCASE', True, bool)
    )
    require_numbers: bool = field(
        default_factory=get_env('IAM_PASSWORD_REQUIRE_NUMBERS', True, bool)
    )
    require_special_characters: bool = field(
        default_factory=get_env('IAM_PASSWORD_REQUIRE_SPECIAL_CHARACTERS', True, bool)
    )


@dataclass
class SignupSettings:
    """Define what information is required for signup."""

    required_fields: list[str] = field(
        default_factory=get_env(
            'IAM_SIGNUP_REQUIRED_FIELDS',
            ['email', 'password', 'first_name', 'last_name'],
            list[str],
        )
    )

    password_policy: PasswordPolicy = field(default_factory=PasswordPolicy)

    def __post_init__(self):
        # Ensure that required_fields is a list of strings

        if (
            get_auth_settings().saas_enabled
            and 'organization_name' not in self.required_fields
        ):
            self.required_fields.append('organization_name')


def get_signup_requirement() -> SignupSettings:
    return SignupSettings()
