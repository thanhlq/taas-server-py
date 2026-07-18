from abc import ABC, abstractmethod
from typing import (
    Dict,
    List,
    Optional,
    Union,
)


class EmailAttachment:
    """Email attachment data."""

    def __init__(self, filename: str, content: bytes, content_type: str):
        self.filename = filename
        self.content = content
        self.content_type = content_type


class EmailMessage:
    """Email message data."""

    def __init__(
        self,
        to: Union[str, List[str]],
        subject: str,
        body: Optional[str] = None,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
        cc: Optional[Union[str, List[str]]] = None,
        bcc: Optional[Union[str, List[str]]] = None,
        html_body: Optional[str] = None,
        attachments: Optional[List[EmailAttachment]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        self.to = to if isinstance(to, list) else [to]
        self.subject = subject
        self.body = body
        self.from_email = from_email
        self.from_name = from_name
        self.cc = cc if isinstance(cc, list) else [cc] if cc else []
        self.bcc = bcc if isinstance(bcc, list) else [bcc] if bcc else []
        self.html_body = html_body
        self.attachments = attachments or []
        self.headers = headers or {}


class IEmailService(ABC):
    """Abstract email service interface."""

    @abstractmethod
    async def send_email(
        self,
        message: EmailMessage,
        template: Optional[str] = None,
        template_data: Optional[dict] = None,
    ) -> str:
        """Send email message. Returns message ID."""
        pass

    # @abstractmethod
    # async def verify_email(self, email: str) -> bool:
    #     """Verify email address format and deliverability."""
    #     pass
