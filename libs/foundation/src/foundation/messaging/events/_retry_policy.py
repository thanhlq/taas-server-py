"""Retry policy lookup for the event processors.

Foundation holds only the retry *definitions*; the implementation is registered
by ``FoundationFactory.use_resiliant(...)`` as an ``IRetryPolicyFactory``.
"""

from __future__ import annotations

from typing import cast

from foundation.resiliant.retry import IRetryPolicy, IRetryPolicyFactory
from foundation.state import get_service


def resolve_retry_policy(name: str, max_attempts: int) -> IRetryPolicy | None:
    """A retry policy from the registered factory, or ``None`` when none is registered."""
    # get_service returns None when raise_if_not_found=False and nothing is registered.
    factory = cast('IRetryPolicyFactory | None', get_service(IRetryPolicyFactory, raise_if_not_found=False))
    return factory.create(name, max_attempts=max_attempts) if factory is not None else None
