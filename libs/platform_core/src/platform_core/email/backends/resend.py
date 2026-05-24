"""Resend email backend using the Resend HTTP API."""

import base64
from typing import TYPE_CHECKING, Any

from platform_core.email.backends.base import BaseEmailBackend
from platform_core.email.exceptions import (
    EmailDeliveryError,
    EmailRateLimitError,
)
from platform_core.email.utils.module_loader import ensure_httpx

if TYPE_CHECKING:
    from platform_core.email.config import ResendConfig
    from platform_core.email.message import EmailMessage
    from platform_core.email.transports.base import HTTPTransport

__all__ = ("ResendBackend",)

RESEND_API_URL = "https://api.resend.com/emails"


class ResendBackend(BaseEmailBackend):
    """Resend email backend using the HTTP API.

    This backend sends emails via Resend's HTTP API, which doesn't require
    SMTP ports and works on any hosting plan.

    The backend uses httpx by default (bundled with Litestar), but can be
    configured to use aiohttp or a custom HTTP transport.

    Example:
        Basic usage::

            config = EmailConfig(
                backend="resend",
                from_email="noreply@example.com",
                backend_config=ResendConfig(api_key="re_xxx..."),
            )
            backend = get_backend("resend", config=config)
            async with backend:
                await backend.send_messages([message])

        Using aiohttp transport::

            config = EmailConfig(
                backend="resend",
                from_email="noreply@example.com",
                backend_config=ResendConfig(
                    api_key="re_xxx...",
                    http_transport="aiohttp",
                ),
            )

    Get your API key at: https://resend.com/api-keys
    """

    __slots__ = ("_config", "_transport")

    def __init__(
        self,
        config: "ResendConfig | None" = None,
        fail_silently: bool = False,
        default_from_email: str | None = None,
        default_from_name: str | None = None,
    ) -> None:
        """Initialize Resend backend.

        Args:
            config: Resend configuration settings. If None, defaults are used.
            fail_silently: If True, suppress exceptions during send.
            default_from_email: Default sender email when message.from_email is missing.
            default_from_name: Default sender name when message.from_email has no name.

        Note:
            May raise ``MissingDependencyError`` if the configured HTTP transport
            is not installed.
        """
        super().__init__(
            fail_silently=fail_silently,
            default_from_email=default_from_email,
            default_from_name=default_from_name,
        )

        # Use provided config or create default
        if config is None:
            from platform_core.email.config import ResendConfig

            config = ResendConfig()

        # Check httpx availability if using default transport
        if config.http_transport == "httpx":
            ensure_httpx()

        self._config = config
        self._transport: "HTTPTransport | None" = None

    async def open(self) -> bool:
        """Open an HTTP transport for sending emails.

        Returns:
            True if a new transport was created, False if reusing existing.
        """
        if self._transport is not None:
            return False

        from platform_core.email.transports import get_transport

        self._transport = get_transport(self._config.http_transport)
        await self._transport.open(
            headers={
                "Authorization": f"Bearer {self._config.api_key}",
                "Content-Type": "application/json",
            },
            timeout=float(self._config.timeout),
        )
        return True

    async def close(self) -> None:
        """Close the HTTP transport."""
        if self._transport is not None:
            try:
                await self._transport.close()
            except Exception:
                if not self.fail_silently:
                    raise
            finally:
                self._transport = None

    async def send_messages(self, messages: list["EmailMessage"]) -> int:
        """Send messages via Resend API.

        Args:
            messages: List of EmailMessage instances to send.

        Returns:
            Number of messages successfully sent.

        Raises:
            EmailDeliveryError: If sending fails and fail_silently is False.
            EmailRateLimitError: If rate limited by the API.
        """
        if not messages:
            return 0

        new_connection = await self.open()

        try:
            num_sent = 0
            for message in messages:
                try:
                    await self._send_message(message)
                    num_sent += 1
                except EmailRateLimitError:
                    # Re-raise rate limit errors for proper handling
                    raise
                except Exception as exc:
                    if not self.fail_silently:
                        msg = f"Failed to send email to {message.to} via Resend"
                        raise EmailDeliveryError(msg) from exc
            return num_sent
        finally:
            if new_connection:
                await self.close()

    async def _send_message(self, message: "EmailMessage") -> None:
        """Send a single message via Resend API.

        Args:
            message: The email message to send.

        Raises:
            RuntimeError: If transport is not initialized.
            EmailRateLimitError: If rate limited by the API.
            EmailDeliveryError: If the API returns an error.
        """
        if self._transport is None:
            msg = "Resend transport not initialized"
            raise RuntimeError(msg)

        # Build the request payload
        _, _, from_formatted = self._resolve_from(message)
        payload: dict[str, Any] = {
            "from": from_formatted,
            "to": message.to,
            "subject": message.subject,
        }

        # Add text body
        if message.body:
            payload["text"] = message.body

        # Add HTML alternative if present
        for content, mimetype in message.alternatives:
            if mimetype == "text/html":
                payload["html"] = content
                break

        # Add optional fields
        if message.cc:
            payload["cc"] = message.cc
        if message.bcc:
            payload["bcc"] = message.bcc
        if message.reply_to:
            # Resend accepts string or list for reply_to
            payload["reply_to"] = message.reply_to[0] if len(message.reply_to) == 1 else message.reply_to

        # Add custom headers
        if message.headers:
            payload["headers"] = message.headers

        # Add attachments with base64 encoding
        if message.attachments:
            payload["attachments"] = [
                {
                    "filename": filename,
                    "content": base64.b64encode(content).decode("ascii"),
                }
                for filename, content, _mimetype in message.attachments
            ]

        response = await self._transport.post(RESEND_API_URL, json=payload)

        # Handle rate limiting
        if response.status_code == 429:
            retry_after = response.get_header("Retry-After")
            retry_seconds = int(retry_after) if retry_after else None
            msg = "Resend API rate limit exceeded"
            raise EmailRateLimitError(msg, retry_after=retry_seconds)

        # Handle other errors
        if response.status_code >= 400:
            error_detail = await response.text()
            msg = f"Resend API error: {response.status_code} - {error_detail}"
            raise EmailDeliveryError(msg)
