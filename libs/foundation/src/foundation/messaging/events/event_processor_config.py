"""
Event Processor Configuration.

Centralized configuration for event processing, retry logic, and DLQ behavior.
"""

from dataclasses import dataclass


@dataclass
class EventProcessorConfig:
    """
    Configuration for EventProcessor.

    This class encapsulates all configuration parameters for event processing,
    retry logic, and error handling.

    Attributes:
        max_retries: Maximum number of retry attempts before sending to DLQ
        retry_backoff_ms: Initial backoff delay in milliseconds for retries
        retry_exponential_base: Base for exponential backoff calculation
        retry_max_delay_ms: Maximum delay between retries in milliseconds
        retry_wait_strategy: Wait strategy ('exponential' or 'fixed')
        enable_dlq: Whether to send failed events to DLQ after max retries
        enable_tracing: Whether to create OpenTelemetry spans for processing
        enable_metrics: Whether to track processing metrics
        retry_policy_name: Name for the retry policy (used in logs/metrics)

    Example:
        >>> config = EventProcessorConfig(
        ...     max_retries=5,
        ...     retry_backoff_ms=2000,
        ...     enable_dlq=True,
        ... )
        >>> processor = EventProcessor(config=config)

        >>> # From settings
        >>> config = EventProcessorConfig.from_settings()
        >>> processor = EventProcessor(config=config)
    """

    # Retry configuration
    retry_enabled: bool = False
    max_retries: int = 3
    retry_backoff_ms: int = 1000
    retry_exponential_base: float = 2.0
    retry_max_delay_ms: int = 60000
    retry_wait_strategy: str = 'exponential'  # or 'fixed'

    # DLQ configuration
    enable_dlq: bool = True

    # Idempotency configuration
    enable_idempotency: bool = False

    # Observability
    enable_tracing: bool = True
    enable_metrics: bool = True

    # Retry policy name (for logging/metrics)
    retry_policy_name: str = 'event_processor'

    # Parallel execution configuration
    enable_parallel_execution: bool = False
    max_concurrent_tasks: int = 10

    def get_retry_initial_delay_seconds(self) -> float:
        """
        Get initial retry delay in seconds.

        Returns:
            Initial delay in seconds
        """
        return self.retry_backoff_ms / 1000.0

    def get_retry_max_delay_seconds(self) -> float:
        """
        Get maximum retry delay in seconds.

        Returns:
            Maximum delay in seconds
        """
        return self.retry_max_delay_ms / 1000.0

    def validate(self) -> None:
        """
        Validate configuration parameters.

        Raises:
            ValueError: If configuration is invalid
        """
        if self.max_retries < 0:
            raise ValueError(f'max_retries must be >= 0, got {self.max_retries}')

        if self.retry_backoff_ms <= 0:
            raise ValueError(
                f'retry_backoff_ms must be > 0, got {self.retry_backoff_ms}'
            )

        if self.retry_exponential_base <= 1.0:
            raise ValueError(
                f'retry_exponential_base must be > 1.0, got {self.retry_exponential_base}'
            )

        if self.retry_max_delay_ms <= 0:
            raise ValueError(
                f'retry_max_delay_ms must be > 0, got {self.retry_max_delay_ms}'
            )

        if self.retry_wait_strategy not in ['exponential', 'fixed']:
            raise ValueError(
                f"retry_wait_strategy must be 'exponential' or 'fixed', got {self.retry_wait_strategy}"
            )

        if self.max_concurrent_tasks <= 0:
            raise ValueError(
                f'max_concurrent_tasks must be > 0, got {self.max_concurrent_tasks}'
            )

    def __post_init__(self):
        """Validate configuration after initialization."""
        self.validate()
