# .venv/lib/python3.13/site-packages/litestar_email/message.py

from __future__ import annotations

from dataclasses import dataclass, field

from foundation.email import EmailConfig, ResendConfig, SMTPConfig
from foundation.utils.env_utils import get_env


@dataclass
class EmailSettings:
    """Email configuration.

    Set EMAIL_BACKEND to:
    - "console" (default) - prints emails to stdout (development)
    - "memory" - stores in memory (testing)
    - "smtp" - sends via SMTP server
    - "resend" - sends via Resend API (production)
    """

    BACKEND: str = field(default_factory=get_env('EMAIL_BACKEND', 'console'))
    """Email backend: console, memory, smtp, resend."""
    FROM_EMAIL: str = field(
        default_factory=get_env('EMAIL_FROM_ADDRESS', 'noreply@localhost')
    )
    """Default from email address."""
    FROM_NAME: str = field(default_factory=get_env('EMAIL_FROM_NAME', 'Litestar App'))
    """Default from name."""
    # SMTP settings (only used when BACKEND="smtp")
    SMTP_HOST: str = field(default_factory=get_env('EMAIL_SMTP_HOST', 'localhost'))
    """SMTP server hostname."""
    SMTP_PORT: int = field(default_factory=get_env('EMAIL_SMTP_PORT', 587, int))
    """SMTP server port."""
    SMTP_USER: str = field(default_factory=get_env('EMAIL_SMTP_USER', ''))
    """SMTP username."""
    SMTP_PASSWORD: str = field(default_factory=get_env('EMAIL_SMTP_PASSWORD', ''))
    """SMTP password."""
    USE_TLS: bool = field(default_factory=get_env('EMAIL_USE_TLS', True))
    """Use TLS for SMTP connection."""
    USE_SSL: bool = field(default_factory=get_env('EMAIL_USE_SSL', False))
    """Use SSL for SMTP connection."""
    TIMEOUT: int = field(default_factory=get_env('EMAIL_TIMEOUT', 30, int))
    """SMTP connection timeout in seconds."""
    # Resend settings (only used when BACKEND="resend")
    RESEND_API_KEY: str = field(default_factory=get_env('RESEND_API_KEY', ''))
    """Resend API key for production email sending."""

    def get_config(self) -> EmailConfig:
        """Return EmailConfig for the litestar-email plugin.

        As of litestar-email v0.3.0, the backend parameter accepts either
        a string ("console", "memory") or a config object (SMTPConfig,
        ResendConfig).

        Returns:
            The email configuration.
        """
        backend: str | SMTPConfig | ResendConfig = self.BACKEND
        if self.BACKEND == 'smtp':
            backend = SMTPConfig(
                host=self.SMTP_HOST,
                port=self.SMTP_PORT,
                username=self.SMTP_USER,
                password=self.SMTP_PASSWORD,
                use_tls=self.USE_TLS,
                use_ssl=self.USE_SSL,
                timeout=self.TIMEOUT,
            )
        elif self.BACKEND == 'resend':
            backend = ResendConfig(api_key=self.RESEND_API_KEY)
        return EmailConfig(
            backend=backend,
            from_email=self.FROM_EMAIL,
            from_name=self.FROM_NAME,
        )
