
from foundation.config import get_settings
from foundation.email.config import EmailConfig
from foundation.email.email_settings import EmailSettings
from foundation.email.service import EmailService
from foundation.email.types import EmailServiceT


class EmailServiceFactory:

    @staticmethod
    def get_email_settings() -> EmailSettings:
        settings = get_settings()
        return settings.email

    @staticmethod
    def get_email_config() -> EmailConfig:
        return EmailServiceFactory.get_email_settings().get_config()

    @staticmethod
    def get_email_service() -> EmailServiceT:

        return EmailService(EmailServiceFactory.get_email_config())
