"""Worker configuration.

Mirrors :mod:`foundation.email.email_settings`: :class:`WorkerSettings` reads
values from environment variables and maps them onto a plain
:class:`WorkerConfig` consumed by :class:`foundation.worker.BaseWorker`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from foundation.observability.types import InstrumentSettings
from foundation.utils.env_utils import get_env


@dataclass(slots=True)
class WorkerConfig:
    """Runtime configuration for a worker application."""

    health_check_enabled: bool = True
    """Whether the health check HTTP server is enabled."""

    health_check_server_port: int = 7000
    """Port for the worker health check HTTP server."""

    health_check_interval_seconds: int = 10
    """Interval (seconds) between health check log emissions."""

    outbox_poller_enabled: bool = True
    """Whether the outbox poller/relay is enabled."""

    # Should take from settings.messaging.CONSUMER_ENABLE
    messaging_consumer_enabled: bool = True

    instrumentation: InstrumentSettings | None = field(default=None)

    instrumentation: InstrumentSettings | None = field(default=None)

    def get_instrumentation_settings(self) -> InstrumentSettings:
        """Return the instrumentation settings for the application.

        Returns:
            The instrumentation settings.
        """
        if self.instrumentation is None:
            self.instrumentation = InstrumentSettings()
        return self.instrumentation

@dataclass
class WorkerSettings:
    """Worker configuration read from environment variables.

    All values are read from environment variables and mapped onto a
    :class:`WorkerConfig` via :meth:`get_config`.
    """

    HEALTH_CHECK_ENABLE: bool = field(
        default_factory=get_env('HEALTH_CHECK_ENABLE', True)
    )
    """Whether the health check HTTP server is enabled."""

    WORKER_LISTEN_PORT: int = field(
        default_factory=get_env('WORKER_LISTEN_PORT', 7000, int)
    )
    """Port for the worker health check HTTP server."""

    HEALTH_CHECK_INTERVAL: int = field(
        default_factory=get_env('HEALTH_CHECK_INTERVAL', 10, int)
    )
    """Interval (seconds) between health check log emissions."""

    OUTBOX_POLLER_ENABLE: bool = field(
        default_factory=get_env('OUTBOX_POLLER_ENABLE', True)
    )
    """Whether the outbox poller/relay is enabled."""

    def get_config(self) -> WorkerConfig:
        """Return the :class:`WorkerConfig` built from these settings.

        Returns:
            The worker configuration.
        """
        return WorkerConfig(
            health_check_enabled=self.HEALTH_CHECK_ENABLE,
            health_check_server_port=self.WORKER_LISTEN_PORT,
            health_check_interval_seconds=self.HEALTH_CHECK_INTERVAL,
            outbox_poller_enabled=self.OUTBOX_POLLER_ENABLE,
        )
