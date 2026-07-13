"""
Event Processor Configuration.

Centralized configuration for event processing, retry logic, and DLQ behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from foundation.messaging.events.event_processor_config import EventProcessorConfig
from foundation.utils.cache import lru_cache_ignore_1st_arg
from foundation.utils.env_utils import get_env


@dataclass
class EventProcessorSettings:
    """Event processor configuration.

    All values are read from environment variables (prefixed with
    ``EVENT_PROCESSOR_``) and mapped onto an :class:`EventProcessorConfig` via
    :meth:`get_config`.
    """

    # Retry configuration
    RETRY_ENABLED: bool = field(
        default_factory=get_env('EVENT_PROCESSOR_RETRY_ENABLED', False)
    )
    """Whether failed events are retried before being sent to the DLQ."""
    MAX_RETRIES: int = field(
        default_factory=get_env('EVENT_PROCESSOR_MAX_RETRIES', 3, int)
    )
    """Maximum number of retry attempts before sending to DLQ."""
    RETRY_BACKOFF_MS: int = field(
        default_factory=get_env('EVENT_PROCESSOR_RETRY_BACKOFF_MS', 1000, int)
    )
    """Initial backoff delay in milliseconds for retries."""
    RETRY_EXPONENTIAL_BASE: str = field(
        default_factory=get_env('EVENT_PROCESSOR_RETRY_EXPONENTIAL_BASE', '2.0')
    )
    """Base for exponential backoff calculation (parsed as float in get_config)."""
    RETRY_MAX_DELAY_MS: int = field(
        default_factory=get_env('EVENT_PROCESSOR_RETRY_MAX_DELAY_MS', 60000, int)
    )
    """Maximum delay between retries in milliseconds."""
    RETRY_WAIT_STRATEGY: str = field(
        default_factory=get_env('EVENT_PROCESSOR_RETRY_WAIT_STRATEGY', 'exponential')
    )
    """Wait strategy: ``exponential`` or ``fixed``."""

    # DLQ configuration
    ENABLE_DLQ: bool = field(
        default_factory=get_env('EVENT_PROCESSOR_ENABLE_DLQ', True)
    )
    """Whether to send failed events to the DLQ after max retries."""

    # Idempotency configuration
    ENABLE_IDEMPOTENCY: bool = field(
        default_factory=get_env('EVENT_PROCESSOR_ENABLE_IDEMPOTENCY', False)
    )
    """Whether idempotency checks are applied to incoming events."""

    # Observability
    ENABLE_TRACING: bool = field(
        default_factory=get_env('EVENT_PROCESSOR_ENABLE_TRACING', True)
    )
    """Whether to create OpenTelemetry spans for processing."""
    ENABLE_METRICS: bool = field(
        default_factory=get_env('EVENT_PROCESSOR_ENABLE_METRICS', True)
    )
    """Whether to track processing metrics."""

    # Retry policy name (for logging/metrics)
    RETRY_POLICY_NAME: str = field(
        default_factory=get_env('EVENT_PROCESSOR_RETRY_POLICY_NAME', 'event_processor')
    )
    """Name for the retry policy (used in logs/metrics)."""

    # Parallel execution configuration
    ENABLE_PARALLEL_EXECUTION: bool = field(
        default_factory=get_env('EVENT_PROCESSOR_ENABLE_PARALLEL_EXECUTION', False)
    )
    """Whether independent tasks may be executed concurrently."""
    MAX_CONCURRENT_TASKS: int = field(
        default_factory=get_env('EVENT_PROCESSOR_MAX_CONCURRENT_TASKS', 10, int)
    )
    """Maximum number of concurrently executed tasks."""

    @lru_cache_ignore_1st_arg
    def get_config(self) -> EventProcessorConfig:
        """Return the :class:`EventProcessorConfig`.

        Returns:
            The event processor configuration (validated on construction).
        """
        return EventProcessorConfig(
            retry_enabled=self.RETRY_ENABLED,
            max_retries=self.MAX_RETRIES,
            retry_backoff_ms=self.RETRY_BACKOFF_MS,
            retry_exponential_base=float(self.RETRY_EXPONENTIAL_BASE),
            retry_max_delay_ms=self.RETRY_MAX_DELAY_MS,
            retry_wait_strategy=self.RETRY_WAIT_STRATEGY,
            enable_dlq=self.ENABLE_DLQ,
            enable_idempotency=self.ENABLE_IDEMPOTENCY,
            enable_tracing=self.ENABLE_TRACING,
            enable_metrics=self.ENABLE_METRICS,
            retry_policy_name=self.RETRY_POLICY_NAME,
            enable_parallel_execution=self.ENABLE_PARALLEL_EXECUTION,
            max_concurrent_tasks=self.MAX_CONCURRENT_TASKS,
        )


@lru_cache
def build_config_from_settings(
    settings: EventProcessorSettings | None = None,
) -> EventProcessorConfig:
    """
    Build an :class:`EventProcessorConfig` from settings.

    Args:
        settings: Optional settings instance. When omitted, a fresh
            :class:`EventProcessorSettings` is read from the environment.

    Returns:
        The event processor configuration.
    """
    settings = settings or EventProcessorSettings()
    return settings.get_config()
