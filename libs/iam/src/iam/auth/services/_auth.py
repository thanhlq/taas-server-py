from __future__ import annotations

from abc import ABC

from foundation.config import Settings, get_settings
from foundation.email.types import EmailMessage, EmailServiceT
from foundation.utils.id import generate_otp

from iam.auth.auth_events import UserRegisteredEvent
from iam.auth.schemas._auth import SignupRequestOut
from iam.auth.types import IamDirectoryServiceT
from iam.common.base import BaseIamService
from iam.iam_constants import IamFrontendRoutes, IamTemplates


class BaseAuthService(BaseIamService, IamDirectoryServiceT, ABC):
    """This is the base class for all authentication services. It provides common functionality and interfaces for different authentication implementations."""

    settings: Settings

    def __init__(self):
        super().__init__()
        self.settings = get_settings()

    @property
    def email_service(self) -> EmailServiceT:
        return self.get_service(EmailServiceT)

    async def signup_01_onboarding_with_email(
        self, email: str, **kwargs
    ) -> SignupRequestOut:
        """
        Handle the first step of user onboarding with email verification.
        This method checks if the email already exists in the system. If it does, it returns a response indicating that the email is already registered. If not, it sends an email verification to the provided email address and returns a response indicating that the verification email has been sent.
        1. Check if the email already exists in the system.
        2. If the email exists, return a response indicating that the email is already registered.
        3. If the email does not exist, send an email verification to the provided email address.
        4. Return a response indicating that the verification email has been sent.
        5. The response includes the email and the status of the operation, which can be 'EXISTED' if the email is already registered or 'VERIFICATION_SENT' if the verification email has been sent successfully.
        6. This method can be used as part of a user registration workflow where email verification is required before proceeding with the registration process.
        """

        count = await self.count_users_by_email(email, **kwargs)

        if count > 0:
            self.logger.info(f'Email {email} already exists in the system.')
            return SignupRequestOut(email=email, status='EXISTED')

        await self.signup_send_email_verification(email, **kwargs)

        return SignupRequestOut(email=email, status='VERIFICATION_SENT')

    async def signup_send_email_verification(self, email: str, **kwargs):
        """
        Send a new account email to the specified address for verification.
        """
        message: EmailMessage = await self.email_service.build_message(
            template=IamTemplates.ACCOUNT_EMAIL_VERIFICATION,
            context={
                'project_name': self.settings.app.NAME,
                'email': email,
                'otp': generate_otp(6),
                'link': f'{self.settings.app.FRONTEND_URL}/{IamFrontendRoutes.VERIFY_ACCOUNT}?email={email}',
            },
            to=[email],
            subject='Verify your new account',
        )

        await self.email_service.send_message(
            message=message,
        )

    async def signup_send_welcome_email(self, user: UserRegisteredEvent, **kwargs):
        """
        Send a new account email to the specified address for verification.
        """

        message: EmailMessage = await self.email_service.build_message(
            template=IamTemplates.WELCOME_EMAIL,
            context={
                'project_name': self.settings.app.NAME,
                'email': user.email,
                'link': f'{self.settings.app.FRONTEND_URL}/{IamFrontendRoutes.VERIFY_ACCOUNT}?email={user.email}',
            },
            to=[user.email],
            subject='Welcome to your new account',
        )

        await self.email_service.send_message(
            message=message,
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
        message: EmailMessage = await self.email_service.build_message(
            template=IamTemplates.WELCOME_EMAIL,
            context={
                'project_name': self.settings.app.NAME,
                'description': description,
                'email': email,
                'otp': otp,
            },
            to=[email],
            subject=title,
        )

        await self.email_service.send_message(
            message=message,
        )
