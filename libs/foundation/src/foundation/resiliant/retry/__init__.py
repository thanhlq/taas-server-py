"""Retry definitions. Implementations (Tenacity, exponential / linear backoff, the
shared ``retry`` decorator instance) live in ``resiliant.retry``."""

from .types import IRetryPolicy, IRetryPolicyFactory

__all__ = [
    'IRetryPolicy',
    'IRetryPolicyFactory',
]
