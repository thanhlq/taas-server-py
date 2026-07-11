from .exp_backoff_retry import ExponentialBackoffRetry
from .retry_tenacity import TenacityRetry

"""
Export a default retry instance configured with sensible defaults for use across the application.
This allows us to have a consistent retry strategy and easily adjust it in one place if needed.
"""
retry = TenacityRetry(
    max_attempts=30,
    initial_delay=1.0,
    max_delay=60.0,
    exponential_base=2.0,
    jitter=True,  # Accepted but ignored
)

# Convenience alias for backward compatibility and common use case
Retry = TenacityRetry

# retry = ExponentialBackoffRetry(
#     max_attempts=30,
#     initial_delay=1.0,
#     max_delay=60.0,
#     exponential_base=2.0,
#     jitter=True,
# )

__all__ = [
    'retry',
    'Retry',
]
