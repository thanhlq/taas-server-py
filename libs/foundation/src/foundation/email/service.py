from typing import Any, cast

from foundation.cli import cli
from foundation.config import get_settings
from foundation.email import EmailConfig
from foundation.email.backends import BaseEmailBackend
from foundation.email.types import EmailMessage, EmailMultiAlternatives, EmailServiceT
from foundation.storage.factory import StorageServiceFactory

__all__ = ('EmailService',)


class EmailService(EmailServiceT):
    """High-level helper for sending email with a configured backend.

    This service is intended for dependency injection in handlers. It can also
    be used directly or as an async context manager to reuse connections.
    Outside of a context manager, each send uses a fresh backend instance.
    """

    __slots__ = ('_backend', '_config', '_subject_prefix')

    def __init__(self, config: 'EmailConfig') -> None:
        """Initialize the email service.

        Args:
            config: The email configuration.
        """
        self._config: EmailConfig = config
        self._backend: BaseEmailBackend | None = None
        self._subject_prefix = f'{get_settings().app.NAME} - '
        """ i.e. eWorksuite - Task assigned """

        init_info: dict[str, Any] = {
            'backend': self.get_configured_email_service_provider(),
            'from_email': self.config.from_email,
            'subject_prefix': self._subject_prefix,
        }
        init_info.update(self.config.info())
        if (not isinstance(self.config.backend, str)) and hasattr(
            self.config.backend, 'info'
        ):
            init_info.update(self.config.backend.info()) # type: ignore

        cli.info_table('Email Service Initialized', init_info)

    @property
    def config(self) -> 'EmailConfig':
        """Return the email configuration."""
        return self._config

    def get_configured_email_service_provider(self) -> str:
        if isinstance(self.config.backend, str):
            return self.config.backend
        else:
            be = cast(BaseEmailBackend, self.config.backend)
            # return class name
            return be.__class__.__name__

    def get_backend(self) -> BaseEmailBackend:
        """Return a backend instance for the configured backend name.

        When the service is not in a context manager, this returns a new backend
        instance each call.
        """
        if self._backend is not None:
            return self._backend
        return self._config.get_backend()

    async def build_message(
        self,
        template: str,
        context: dict[str, str],
        *,
        to: list[str],
        subject: str | None = None,
        from_email: str | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        attachments: list[tuple[str, bytes, str]] | None = None,
        alternatives: list[tuple[str, str]] | None = None,
    ) -> 'EmailMultiAlternatives':
        """Build an email message from a template.

        Args:
            template: The name of the template to use.
            context: The context to render the template with.
            to: List of recipient email addresses.
            subject: Optional subject for the email. If not provided, the template's subject will be used.
            from_email: Optional sender email address. If not provided, the default from_email will be used.
            cc: Optional list of CC recipient email addresses.
            bcc: Optional list of BCC recipient email addresses.
            attachments: Optional list of attachments as tuples (filename, content, mimetype).
            alternatives: Optional list of alternative content as tuples (content, mimetype).
        """
        template_svc = StorageServiceFactory.get_template_storage_service()
        template_content = await template_svc.get_template(template)
        body: str = await template_svc.render_template(
            template_content,
            context=context,
        )

        subject = f'{self._subject_prefix}{subject}'

        message = EmailMultiAlternatives(
            to=to,
            # body=body,
            html_body=body,
            subject=subject,
            from_email=from_email or self.config.from_email,
            cc=cc or [],
            bcc=bcc or [],
            attachments=attachments or [],
            alternatives=alternatives or [],
        )

        return message

    async def send_messages(self, messages: list['EmailMessage']) -> int:
        """Send a list of email messages.

        Args:
            messages: List of EmailMessage instances.

        Returns:
            Number of messages sent.
        """
        if not messages:
            return 0

        if self._backend is not None:
            return await self._backend.send_messages(messages)

        backend = self._config.get_backend()
        try:
            await backend.open()
            return await backend.send_messages(messages)
        finally:
            await backend.close()

    async def send_message(self, message: 'EmailMessage') -> int:
        """Send a single email message.

        Args:
            message: The email message to send.

        Returns:
            Number of messages sent (0 or 1).
        """
        return await self.send_messages([message])

    async def __aenter__(self) -> 'EmailService':
        if self._backend is None:
            self._backend = self._config.get_backend()
            await self._backend.open()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        if self._backend is not None:
            await self._backend.close()
            self._backend = None
