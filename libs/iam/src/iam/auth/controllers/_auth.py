from __future__ import annotations

from foundation.config.saas_settings import get_saas_settings
from foundation.db.advanced_db_manager import (
    db_concurrent_session,
)
from foundation.db.types import DBAsyncScopedSession
from foundation.http import BaseController, cache, get, post, status
from foundation.utils.validation import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH

from iam.auth.schemas import SignupRequest
from iam.auth.schemas._auth import SignupEmailVerification, SignupRequestOut
from iam.types import IIamServiceFactory


def get_iam_service_factory() -> IIamServiceFactory:
    from iam.iam_factory import IamFactory

    return IamFactory.get_iam_service_factory()


class AuthController(BaseController):
    """Authentication Controller."""

    api_prefix = '/api/v1/auth'
    tags = ('Authentication',)

    @get('/signup-info')
    @db_concurrent_session
    @cache(expire=60)  # Cache the response for 60 seconds
    async def get_signup_info(self, session: DBAsyncScopedSession) -> dict:
        info = {
            'signup_enabled': True,
            'pre_email_verification_required': True,
            'password_policy': {
                'min_length': PASSWORD_MIN_LENGTH,
                'max_length': PASSWORD_MAX_LENGTH,
                'require_uppercase': True,
                'require_lowercase': True,
                'require_numbers': True,
                'require_special_characters': True,
            },
            'required_fields': ['email', 'password', 'first_name', 'last_name'],
            # 'organization_policy': {
            #     'required_fields': ['organization_name'],
            #     'require_domain_verification': False,
            # },
        }
        if get_saas_settings().saas_enabled:
            info['required_fields'].append('organization_name') # type: ignore

        return info

    # ratelimit='5000/minute' does not work
    @post('/signup/email-verification', status_code=status.HTTP_201_CREATED)
    async def signup_01_verify_email(
        self, data: SignupEmailVerification
    ) -> SignupRequestOut:

        # users_service = UserAccountFactory.get_user_service(session)
        signup_service = get_iam_service_factory().get_directory_signup_service()

        return await signup_service.signup_01_onboarding_with_email(data.email)

    @post('/signup', status_code=status.HTTP_201_CREATED)
    async def signup_02_submit(self, data: SignupRequest) -> SignupRequestOut:

        # users_service = UserAccountFactory.get_user_service(session)
        signup_service = get_iam_service_factory().get_directory_signup_service()

        return await signup_service.signup_02_submit(data)
