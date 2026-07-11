"""
Definition of common patterns for resilience services, such as:
  - Circuit breakers: a pattern for preventing cascading failures and improving system stability by temporarily blocking access to a service or resource that is experiencing failures, often with configurable thresholds and timeouts.
  - Outbox: a pattern for ensuring reliable message delivery in distributed systems, often used to decouple services and improve fault tolerance by persisting messages in a durable store before processing or sending them to their destination.
  - Saga: a pattern for managing long-running transactions and distributed workflows, often used to ensure data consistency and handle failures in microservices architectures.
  - Idempotency: a pattern for ensuring that repeated requests with the same idempotency key have the same effect, often used to prevent duplicate processing of requests in distributed systems. This module defines the data structures and exceptions related to idempotency, including:
  - Retry policies: a pattern for automatically retrying failed operations, often with configurable backoff strategies and limits on the number of retries.
  - Bulkheads: a pattern for isolating resources and limiting concurrent access to prevent cascading failures and improve system stability.
  - Timeouts: a pattern for enforcing limits on the duration of operations, often used to prevent cascading failures and improve system responsiveness.
  - Fallbacks: a pattern for providing alternative behavior or responses when a service is unavailable or fails, often used in conjunction with circuit breakers and timeouts.
  - Dead letter queues: a pattern for handling messages that cannot be processed successfully after multiple attempts, often used in conjunction with message queues or event-driven architectures.
"""
