from __future__ import annotations

from abc import ABC

from foundation import BaseService
from foundation.config import Settings, get_settings
from foundation.email.types import EmailMessage, IEmailService
from foundation.utils.id import generate_otp

from iam.auth.auth_events import UserRegisteredEvent
from iam.auth.types import IamDirectoryServiceT
from iam.iam_constants import IamFrontendRoutes, IamTemplates


class BaseAuthService(BaseService, IamDirectoryServiceT, ABC):
    settings: Settings

    def __init__(self):
        super().__init__()
        self.settings = get_settings()

    @property
    def email_service(self) -> IEmailService:
        return self.get_service(IEmailService)

    async def signup_send_email_verification(self, user: UserRegisteredEvent, **kwargs):
        """
        Send a new account email to the specified address for verification.
        """

        to_email = user.email

        message = EmailMessage(
            to=to_email,
            subject=f'{self.settings.app.NAME} - Verify your new account',
        )

        await self.email_service.send_email(
            message=message,
            template=IamTemplates.ACCOUNT_EMAIL_VERIFICATION,
            template_data={
                'project_name': self.settings.app.NAME,
                'email': to_email,
                'otp': generate_otp(6),
                'link': f'{self.settings.app.FRONTEND_URL}/{IamFrontendRoutes.VERIFY_ACCOUNT}?email={to_email}',
            },
        )

    async def signup_send_welcome_email(self, user: UserRegisteredEvent, **kwargs):
        """
        Send a new account email to the specified address for verification.
        """

        to_email = user.email
        message = EmailMessage(
            to=to_email,
            subject=f'{self.settings.app.NAME} - Welcome to your new account',
        )

        await self.email_service.send_email(
            message=message,
            template=IamTemplates.WELCOME_EMAIL,
            template_data={
                'project_name': self.settings.app.NAME,
                'email': to_email,
                'link': f'{self.settings.app.FRONTEND_URL}/{IamFrontendRoutes.VERIFY_ACCOUNT}?email={to_email}',
            },
        )

    async def signup_send_otp_to_email(
        self,
        email: str,
        otp: str | None = None,
        title: str | None = None,
        description: str | None = None,
    ):
        """Send OTP to the specified email address.
        This can be used for email verification, password resets, transaction verification, etc.
        """
        title = (
            title if title else f'{self.settings.app.NAME} - Verify your email address'
        )
        description = (
            description
            if description
            else 'Use the following OTP to verify your email address.'
        )
        otp = otp if otp else generate_otp()

        message = EmailMessage(
            to=email,
            subject=title,
        )

        await self.email_service.send_email(
            message=message,
            template=IamTemplates.USER_OTP,
            template_data={
                'project_name': self.settings.app.NAME,
                'description': description,
                'email': email,
                'otp': otp,
                # 'link': f'{self.settings.DOMAIN_FRONTEND}/{IamFrontendRoutes.VERIFY_ACCOUNT}?email={to_email}',
            },
        )
