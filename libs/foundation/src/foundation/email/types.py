from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class EmailAttachment:
    """Email attachment data."""

    def __init__(self, filename: str, content: bytes, content_type: str):
        self.filename = filename
        self.content = content
        self.content_type = content_type


@dataclass(slots=True)
class EmailMessage:
    """A container for email message data.

    This dataclass holds all the information needed to send an email,
    including recipients, content, and optional attachments.
    """


    subject: str
    body: str | None = None
    from_email: str | None = None
    to: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    reply_to: list[str] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
    attachments: list[tuple[str, bytes, str]] = field(default_factory=list)
    alternatives: list[tuple[str, str]] = field(default_factory=list)

    def attach(self, filename: str, content: bytes, mimetype: str) -> None:
        """Add an attachment to the email.

        Args:
            filename: The name of the attachment file.
            content: The binary content of the attachment.
            mimetype: The MIME type of the attachment (e.g., "application/pdf").
        """
        self.attachments.append((filename, content, mimetype))

    def attach_alternative(self, content: str, mimetype: str) -> None:
        """Add an alternative content representation.

        Typically used to add an HTML version of the email alongside
        the plain text body.

        Args:
            content: The alternative content (e.g., HTML).
            mimetype: The MIME type (e.g., "text/html").
        """
        self.alternatives.append((content, mimetype))

    def recipients(self) -> list[str]:
        """Return all recipients of the email.

        Returns:
            A combined list of all to, cc, and bcc recipients.
        """
        return self.to + self.cc + self.bcc


@dataclass(slots=True)
class EmailMultiAlternatives(EmailMessage):
    """An email message with HTML content support.

    This convenience class extends EmailMessage to automatically
    attach an HTML body as an alternative representation.
    """

    html_body: str | None = None

    def __post_init__(self) -> None:
        """Automatically attach html_body as an alternative if provided."""
        if self.html_body is not None:
            self.attach_alternative(self.html_body, 'text/html')


class EmailServiceT(ABC):
    """Abstract email service interface."""

    @abstractmethod
    def get_configured_email_service_provider(self) -> str: ...

    @abstractmethod
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
    ) -> 'EmailMessage': ...

    @abstractmethod
    async def send_message(self, message: 'EmailMessage') -> int: ...

    @abstractmethod
    async def send_messages(self, messages: list['EmailMessage']) -> int: ...
