"""
Definition of common patterns for resilience services, such as:
  - Circuit breakers
  - Outbox
  - Saga
  - Idempotency
  - Retry policies
  - Bulkheads
  - Timeouts
  - Fallbacks
"""

from .register_services import register_factory

__all__ = ["register_resiliant_service_factory"]
