"""Retry implementations (definitions: ``foundation.resiliant.retry``).

* :class:`TenacityRetry` — default policy (``Retry`` alias)
* :class:`ExponentialBackoffRetry`, :class:`LinearBackoffRetry` — dependency-free policies
* :data:`retry` — shared instance for decorating start-up / connection code
* :class:`TenacityRetryPolicyFactory` — ``IRetryPolicyFactory`` registered for foundation
"""

from foundation.resiliant.retry import IRetryPolicy, IRetryPolicyFactory

from ._exp_backoff_retry import ExponentialBackoffRetry, LinearBackoffRetry
from ._retry_tenacity import TenacityRetry

# Convenience alias: the default retry policy class.
Retry = TenacityRetry

retry = TenacityRetry(
    max_attempts=30,
    initial_delay=1.0,
    max_delay=60.0,
    exponential_base=2.0,
    jitter=True,  # Accepted but ignored
)
"""Shared instance with patient defaults (30 attempts, up to 60 s apart), e.g.
``@retry.decorator(name='start_kafka_producer')``."""


class TenacityRetryPolicyFactory(IRetryPolicyFactory):
    """Builds :class:`TenacityRetry` policies for foundation code."""

    def create(
        self,
        name: str,
        *,
        max_attempts: int = 3,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
    ) -> IRetryPolicy:
        return TenacityRetry(
            name=name, max_attempts=max_attempts, initial_delay=initial_delay, max_delay=max_delay
        )


__all__ = [
    'ExponentialBackoffRetry',
    'LinearBackoffRetry',
    'Retry',
    'TenacityRetry',
    'TenacityRetryPolicyFactory',
    'retry',
]
