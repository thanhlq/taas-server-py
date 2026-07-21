from __future__ import annotations

from foundation.http import BaseController, post, status
from iam.auth.schemas import SignupRequest
from iam.auth.schemas._auth import SignupEmailVerification, SignupRequestOut
from iam.types import IIamServiceFactory


def get_iam_service_factory() -> IIamServiceFactory:
    from iam.iam_factory import IamFactory

    return IamFactory.get_iam_service_factory()


class TenantController(BaseController):
    """Tenant Controller."""

    api_prefix = '/api/v1/tenant/admin'
    tags = ('Tenant Administration',)


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
