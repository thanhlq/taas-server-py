from __future__ import annotations

from abc import ABC
from datetime import timedelta

from foundation.config import Settings, get_settings
from foundation.email.types import EmailMessage, EmailServiceT
from foundation.utils.id import generate_otp

from iam.auth.auth_events import UserRegisteredEvent
from iam.auth.schemas import SignupRequest
from iam.auth.schemas._auth import SignupRequestOut
from iam.auth.types import IamDirectoryServiceT
from iam.common.base import BaseIamService
from iam.iam_constants import IamConstants, IamFrontendRoutes, IamTemplates
from iam.utils.cache_key_builder import IamCacheKeyBuilder


class BaseAuthService(BaseIamService, IamDirectoryServiceT, ABC):
    """This is the base class for all authentication services. It provides common functionality and interfaces for different authentication implementations."""

    settings: Settings

    def __init__(self):
        super().__init__()
        self.settings = get_settings()

    @property
    def email_service(self) -> EmailServiceT:
        return self.get_service(EmailServiceT)

    # ---------------------------------------------------------------------------
    # SIGNUP
    # ---------------------------------------------------------------------------

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

        await self.send_otp_to_email(
            email,
            subject='Verify your new account',
            link=f'{self.settings.app.FRONTEND_URL}/{IamFrontendRoutes.VERIFY_ACCOUNT}?email={email}',
            **kwargs,
        )

        return SignupRequestOut(email=email, status='VERIFICATION_SENT')

    async def signup_02_submit(self, data: SignupRequest, **kwargs) -> SignupRequestOut:

        return await self.directory_service.create_directory_user(data, **kwargs)



    async def send_otp_to_email(self, email: str,
                                *,
                                subject: str | None = 'Here is your verification code',
                                otp: str | None = None,
                                link: str | None = None,
                                description: str | None = None,
                                **kwargs):
        """
        Send a new account email to the specified address for verification.
        """


        # 01. Build message
        _otp = otp or generate_otp()
        # _link = link or f'{self.settings.app.FRONTEND_URL}/{IamFrontendRoutes.VERIFY_ACCOUNT}?email={email}'
        description = description or 'Use the following OTP to verify your email address.'

        message: EmailMessage = await self.email_service.build_message(
            template=IamTemplates.ACCOUNT_EMAIL_VERIFICATION,
            context={
                'project_name': self.settings.app.NAME,
                'email': email,
                'otp': _otp,
                'link': link,
                'description': description,
                **kwargs,
            },
            to=[email],
            subject=subject,
        )

        # 02. Store the OTP in the database or cache for later verification (not shown here, but should be implemented in a real application)
        await self.cache_service.set(
                IamCacheKeyBuilder.build_signup_otp_key(email),
                f'{otp}:{email}',
                timedelta(seconds=IamConstants.OTP_SIGNUP_EMAIL_VALIDITY_SECONDS),
            )


        # 03. Send the email
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
