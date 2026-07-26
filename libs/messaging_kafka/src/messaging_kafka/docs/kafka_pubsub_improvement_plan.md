# 📋 Kafka Pub/Sub & Event Processor - Improvement Plan

**Date:** January 17, 2026
**Status:** Planning Phase
**Priority:** High
**Affected Files:**
- `libs/core/src/core/kafka/kafka_pubsub.py`
- `libs/core/src/core/common/event_processor.py`
- `libs/core/src/core/common/event_handler.py`

---

## 📊 Executive Summary

**Overall Assessment: 7.5/10**

The current Kafka pub/sub implementation demonstrates solid architecture with clean separation of concerns and good error handling. However, several critical issues need addressing to ensure production reliability, particularly around retry mechanisms, distributed tracing, and idempotency.

### Strengths ✅
- Clean separation of concerns (EventProcessor decoupled from Kafka)
- Good error handling structure with DLQ pattern
- OpenTelemetry integration for observability
- Comprehensive test coverage
- Proper resource management and graceful shutdown

### Critical Issues 🔴
- Retry counter double-counting bug
- Broken distributed tracing (commented-out code)
- Missing idempotency protection
- Inconsistent error handling in subscriptions
- No connection health monitoring
- Incomplete backpressure handling

---

## 🔴 Critical Priority Issues

### 1. Fix Retry Mechanism Double-Counting

**File:** `libs/core/src/core/common/event_processor.py`
**Lines:** 130-157
**Severity:** CRITICAL

#### Problem
The retry counter is incremented twice in certain scenarios, leading to:
- Inconsistent retry counts in logs and metrics
- Messages sent to DLQ prematurely
- Confusion in debugging failed events

**Current Code:**
```python
# Lines 130-157 in event_processor.py
try:
    result = await handler.handle(event)
    if not result.success:
        is_handler_exception = False
        # ❌ ISSUE: Increment here
        event.metadata.retry_count += 1
        self.stats['messages_retried'] += 1
        error = Exception(result.error or 'Handler returned failure')
        span.record_exception(error)
        raise error
    return result

except Exception as e:
    if is_handler_exception:
        # ❌ ISSUE: And increment here again (double count)
        event.metadata.retry_count += 1
        self.stats['messages_retried'] += 1
```

#### Root Cause
1. When handler returns `success=False`, code increments `retry_count`
2. Then raises an exception
3. Exception handler increments `retry_count` again
4. Result: retry count is off by 1

#### Proposed Solution

```python
async def process_event(
    self,
    event: BaseEvent,
    traceparent: Optional[str] = None,
    handler: Optional[BaseEventHandler] = None,
) -> ProcessingResult:
    # Get handler from registry if not provided
    if handler is None:
        handler = registry.get_handler(event.metadata.event_type)

    if not handler:
        return ProcessingResult(
            success=False,
            event_id=event.metadata.event_id,
            processing_time_ms=0,
            error=f'No handler for event type: {event.metadata.event_type}',
        )

    # ✅ CHECK: Verify we haven't exceeded max retries BEFORE attempting
    if event.metadata.retry_count >= self.config.MAX_RETRIES:
        return ProcessingResult(
            success=False,
            event_id=event.metadata.event_id,
            processing_time_ms=0,
            error=f'Max retries ({self.config.MAX_RETRIES}) exceeded',
            retry_count=event.metadata.retry_count,
        )

    start_time = time.time()
    handler_name = handler.__class__.__name__
    event.metadata.handler_name = handler_name

    # Process with retry logic
    @retry(
        stop=stop_after_attempt(self.config.MAX_RETRIES),
        wait=wait_exponential(
            multiplier=1,
            min=self.config.RETRY_BACKOFF_MS / 1000,
            max=60,
        ),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    async def process_with_tenacity():
        ContextTracer = TracingFactory().get_context_tracer()

        with ContextTracer(handler_name, traceparent) as span:
            span.set_attribute('handler_name', handler_name)
            span.set_attribute('event_id', event.metadata.event_id)
            span.set_attribute('event_type', event.metadata.event_type)
            span.set_attribute('retry_count', event.metadata.retry_count)

            try:
                result = await handler.handle(event)
                result.processing_time_ms = (time.time() - start_time) * 1000
                result.handler_name = handler_name

                if not result.success:
                    # Convert handler failure to exception for tenacity retry
                    error = Exception(result.error or 'Handler returned failure')
                    span.record_exception(error)
                    raise error

                return result

            except Exception as e:
                # ✅ FIX: Increment retry count only once, here
                event.metadata.retry_count += 1
                self.stats['messages_retried'] += 1

                self.logger.error(
                    f'Handler exception: handler={handler_name}, '
                    f'event_id={event.metadata.event_id}, '
                    f'retry_count={event.metadata.retry_count}, '
                    f'error={str(e)}'
                )
                span.record_exception(e)
                raise e

    try:
        return await process_with_tenacity()
    except Exception as e:
        # Return structured result for DLQ processing
        return ProcessingResult(
            success=False,
            event_id=event.metadata.event_id,
            processing_time_ms=(time.time() - start_time) * 1000,
            error=str(e),
            retry_count=event.metadata.retry_count,
            handler_name=handler_name,
        )
```

#### Testing Strategy
1. Unit test: Handler returns `success=False` → verify retry_count increments correctly
2. Unit test: Handler throws exception → verify retry_count increments correctly
3. Integration test: Verify max retries triggers DLQ correctly
4. Load test: Monitor stats accuracy under high load

#### Impact
- Fixes incorrect retry counts in logs and metrics
- Ensures DLQ is triggered at correct retry threshold
- Improves debugging accuracy

---

### 2. Fix Trace Context Propagation

**File:** `libs/core/src/core/common/event_processor.py`
**Lines:** 95-106
**Severity:** CRITICAL

#### Problem
Distributed tracing is broken because trace context extraction code is commented out:

```python
# Lines 95-106 - ALL COMMENTED OUT!
# Extract trace context from carrier
# ctx = None
# if traceparent:
#     carrier = {'traceparent': traceparent}
#     ctx = TraceContextTextMapPropagator().extract(carrier=carrier)
# else:
#     self.logger.warning(
#         f'No traceparent provided for event: event_id={event.metadata.event_id}'
#     )
```

#### Impact
- Parent-child span relationships are broken
- Cannot trace requests across service boundaries
- Observability severely degraded in distributed systems

#### Proposed Solution

```python
async def process_event(
    self,
    event: BaseEvent,
    traceparent: Optional[str] = None,
    handler: Optional[BaseEventHandler] = None,
) -> ProcessingResult:
    # ... (handler lookup code)

    start_time = time.time()
    handler_name = handler.__class__.__name__
    event.metadata.handler_name = handler_name

    # ✅ FIX: Extract trace context from carrier
    trace_context = None
    if traceparent:
        carrier = {'traceparent': traceparent}
        try:
            trace_context = TraceContextTextMapPropagator().extract(carrier=carrier)
            self.logger.debug(
                f'Extracted trace context: event_id={event.metadata.event_id}, '
                f'traceparent={traceparent}'
            )
        except Exception as e:
            self.logger.warning(
                f'Failed to extract trace context: event_id={event.metadata.event_id}, '
                f'error={str(e)}'
            )
    else:
        self.logger.debug(
            f'No traceparent provided for event: event_id={event.metadata.event_id}, '
            f'event_type={event.metadata.event_type}'
        )

    # Process with retry logic
    @retry(...)
    async def process_with_tenacity():
        ContextTracer = TracingFactory().get_context_tracer()

        # ✅ FIX: Pass trace context to ContextTracer
        # Note: Verify ContextTracer supports context parameter
        with ContextTracer(handler_name, traceparent, context=trace_context) as span:
            # ... (rest of processing logic)
```

#### Additional Changes Needed

**Verify ContextTracer Implementation:**
Check if `ContextTracer` (from `TracingFactory().get_context_tracer()`) supports context parameter. If not, update it:

```python
# In otel_tracing.py or wherever ContextTracer is defined
class OtelContextTracer:
    def __init__(self, span_name: str, traceparent: Optional[str] = None,
                 context: Optional[Context] = None):
        self.span_name = span_name
        self.traceparent = traceparent
        self.context = context  # ✅ Add context parameter

    def __enter__(self):
        # If context provided, use it; otherwise use current context
        ctx = self.context or context_api.get_current()
        self.token = context_api.attach(ctx)
        self.span = tracer.start_span(self.span_name)
        # ...
```

#### Testing Strategy
1. Create integration test with producer → Kafka → consumer chain
2. Verify traceparent header is propagated through Kafka
3. Verify parent-child span relationships in trace backend (Jaeger/Tempo)
4. Test trace continuation after retries

---

### 3. Add Idempotency Handling

**Severity:** HIGH
**Effort:** Medium

#### Problem
Kafka guarantees at-least-once delivery, which means:
- Messages can be delivered multiple times (network issues, rebalancing, retries)
- Handlers might process the same event twice
- No deduplication mechanism exists

#### Consequences
- Duplicate email sends
- Double payments
- Inconsistent state in downstream systems

#### Proposed Solution

**Step 1: Create Idempotency Service**

```python
# File: libs/core/src/core/common/idempotency.py

from abc import ABC, abstractmethod
from typing import Optional
import hashlib
import json

class IIdempotencyCache(ABC):
    """Interface for idempotency tracking."""

    @abstractmethod
    async def is_processed(self, event_id: str) -> bool:
        """Check if event has been processed."""
        pass

    @abstractmethod
    async def mark_processed(self, event_id: str, ttl_seconds: int = 86400) -> None:
        """Mark event as processed with TTL."""
        pass

    @abstractmethod
    async def get_result(self, event_id: str) -> Optional[dict]:
        """Get cached processing result."""
        pass


class RedisIdempotencyCache(IIdempotencyCache):
    """Redis-based idempotency cache."""

    def __init__(self, redis_client):
        self.redis = redis_client
        self.key_prefix = "idempotency:event:"

    async def is_processed(self, event_id: str) -> bool:
        key = f"{self.key_prefix}{event_id}"
        return await self.redis.exists(key) > 0

    async def mark_processed(self, event_id: str, ttl_seconds: int = 86400) -> None:
        key = f"{self.key_prefix}{event_id}"
        await self.redis.setex(key, ttl_seconds, "processed")

    async def get_result(self, event_id: str) -> Optional[dict]:
        key = f"{self.key_prefix}{event_id}:result"
        data = await self.redis.get(key)
        return json.loads(data) if data else None

    async def cache_result(self, event_id: str, result: dict, ttl_seconds: int = 86400) -> None:
        key = f"{self.key_prefix}{event_id}:result"
        await self.redis.setex(key, ttl_seconds, json.dumps(result))


class MemoryIdempotencyCache(IIdempotencyCache):
    """In-memory idempotency cache (for testing/development)."""

    def __init__(self):
        self._cache = {}
        self._results = {}

    async def is_processed(self, event_id: str) -> bool:
        return event_id in self._cache

    async def mark_processed(self, event_id: str, ttl_seconds: int = 86400) -> None:
        self._cache[event_id] = True
        # Note: TTL not implemented in memory version

    async def get_result(self, event_id: str) -> Optional[dict]:
        return self._results.get(event_id)

    async def cache_result(self, event_id: str, result: dict, ttl_seconds: int = 86400) -> None:
        self._results[event_id] = result
```

**Step 2: Integrate into EventProcessor**

```python
# File: libs/core/src/core/common/event_processor.py

class EventProcessor:
    def __init__(
        self,
        stats: Optional[dict] = None,
        idempotency_cache: Optional[IIdempotencyCache] = None
    ):
        self.config = get_app_settings()
        self.logger = LogFactory().get_logger(self.__class__.__name__)
        self._internal_stats = {'messages_retried': 0}
        self.stats = stats or self._internal_stats

        # ✅ ADD: Idempotency cache
        self.idempotency_cache = idempotency_cache
        self.enable_idempotency = idempotency_cache is not None

    async def process_event(
        self,
        event: BaseEvent,
        traceparent: Optional[str] = None,
        handler: Optional[BaseEventHandler] = None,
    ) -> ProcessingResult:
        # ✅ ADD: Check idempotency BEFORE processing
        if self.enable_idempotency:
            if await self.idempotency_cache.is_processed(event.metadata.event_id):
                self.logger.info(
                    f'Event already processed (idempotent): '
                    f'event_id={event.metadata.event_id}'
                )

                # Return cached result if available
                cached_result = await self.idempotency_cache.get_result(
                    event.metadata.event_id
                )
                if cached_result:
                    return ProcessingResult(**cached_result)

                # Or return success without re-processing
                return ProcessingResult(
                    success=True,
                    event_id=event.metadata.event_id,
                    processing_time_ms=0,
                    error=None,
                )

        # ... (existing handler lookup and processing code)

        try:
            result = await process_with_tenacity()

            # ✅ ADD: Mark as processed after successful handling
            if result.success and self.enable_idempotency:
                await self.idempotency_cache.mark_processed(
                    event.metadata.event_id,
                    ttl_seconds=self.config.IDEMPOTENCY_TTL_SECONDS
                )
                # Optionally cache the result
                await self.idempotency_cache.cache_result(
                    event.metadata.event_id,
                    result.model_dump()
                )

            return result

        except Exception as e:
            # ... (existing error handling)
```

**Step 3: Add Configuration**

```python
# File: libs/core/src/core/conf/settings.py

class AppSettings(BaseSettings):
    # ... existing settings

    # Idempotency settings
    ENABLE_IDEMPOTENCY: bool = Field(
        default=True,
        description='Enable idempotency checking for event processing'
    )
    IDEMPOTENCY_TTL_SECONDS: int = Field(
        default=86400,  # 24 hours
        description='How long to cache processed event IDs'
    )
    IDEMPOTENCY_BACKEND: str = Field(
        default='redis',
        description='Backend for idempotency cache: redis, memory'
    )
```

**Step 4: Update KafkaPubSubService**

```python
# File: libs/core/src/core/kafka/kafka_pubsub.py

class KafkaPubSubService(AbstractService, IPubSubService):
    def __init__(self):
        # ... existing initialization

        # ✅ ADD: Initialize idempotency cache
        idempotency_cache = None
        if self.config.ENABLE_IDEMPOTENCY:
            if self.config.IDEMPOTENCY_BACKEND == 'redis':
                # Get Redis client from dependency injection or create one
                redis_client = get_redis_client()
                idempotency_cache = RedisIdempotencyCache(redis_client)
            else:
                idempotency_cache = MemoryIdempotencyCache()

        # Initialize event processor with idempotency cache
        self.event_processor = EventProcessor(
            stats=self.stats,
            idempotency_cache=idempotency_cache
        )
```

#### Testing Strategy
1. Test duplicate message delivery → verify only processed once
2. Test cached result retrieval
3. Test TTL expiration → verify re-processing after TTL
4. Performance test: measure cache overhead
5. Test with Redis unavailable → graceful degradation

#### Rollout Plan
1. Phase 1: Deploy with `ENABLE_IDEMPOTENCY=false` (default off)
2. Phase 2: Enable in staging with monitoring
3. Phase 3: Enable in production for non-critical topics
4. Phase 4: Enable globally

---

## 🟡 High Priority Issues

### 4. Improve Error Handling in subscribe()

**File:** `libs/core/src/core/kafka/kafka_pubsub.py`
**Lines:** 558-579
**Severity:** HIGH

#### Problem
The `subscribe()` method has inconsistent error handling compared to the main consumption loop:

```python
async for message in consumer:
    try:
        # ...decode and call handler
        await handler(data)
    except Exception as e:
        self.logger.error(f'Handler error...', exc_info=True)
        # ❌ No retry logic
        # ❌ No DLQ
        # ❌ No stats tracking
        # ❌ Inconsistent with _process_message()
```

#### Proposed Solution

```python
async def subscribe(self, topic: str, handler: MessageHandler) -> str:
    """
    Subscribe to topic with handler. Returns subscription ID.

    Now includes retry logic and DLQ for consistency with main consumer.
    """
    if not self.running:
        raise RuntimeError('Service not running. Call start() first.')

    subscription_id = str(uuid.uuid4())

    # Create dedicated consumer for this subscription
    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=self.config.kafka_bootstrap_servers_list,
        group_id=f'{self.config.KAFKA_CONSUMER_GROUP_ID}_{subscription_id}',
        auto_offset_reset='latest',
        enable_auto_commit=True,
    )

    await consumer.start()

    # ✅ FIX: Create wrapper handler that returns ProcessingResult
    class SubscriptionHandler(BaseEventHandler):
        def __init__(self, wrapped_handler: MessageHandler):
            self.wrapped_handler = wrapped_handler

        async def handle(self, event: BaseEvent) -> ProcessingResult:
            try:
                # Call original handler
                await self.wrapped_handler(event.payload)
                return ProcessingResult(
                    success=True,
                    event_id=event.metadata.event_id,
                )
            except Exception as e:
                return ProcessingResult(
                    success=False,
                    event_id=event.metadata.event_id,
                    error=str(e),
                )

    wrapped_handler = SubscriptionHandler(handler)

    # Create background task to consume messages
    async def consume_for_subscription() -> None:
        try:
            self.logger.info(
                f'Started subscription: id={subscription_id}, topic={topic}'
            )

            async for message in consumer:
                if not self.running:
                    break

                try:
                    # Skip if message value is None
                    if message.value is None:
                        continue

                    # Extract traceparent from headers
                    traceparent: str | None = None
                    if message.headers:
                        for header_key, header_value in message.headers:
                            if 'traceparent' == header_key:
                                traceparent = header_value.decode('utf-8')
                                break

                    # Decode message
                    raw_data = message.value.decode('utf-8')
                    data = json.loads(raw_data)

                    # Parse as BaseEvent
                    event = BaseEvent(**data)

                    # ✅ FIX: Process with EventProcessor (includes retry + DLQ)
                    result = await self.event_processor.process_event(
                        event,
                        traceparent=traceparent,
                        handler=wrapped_handler
                    )

                    if result.success:
                        self.stats['messages_processed'] += 1
                    else:
                        self.stats['messages_failed'] += 1

                        # Send to DLQ if max retries exceeded
                        if event.metadata.retry_count >= self.config.MAX_RETRIES:
                            await self._send_to_dlq(event, result.error, traceparent)
                            self.stats['messages_dlq'] += 1

                except json.JSONDecodeError as e:
                    self.logger.error(
                        f'Subscription decode error: id={subscription_id}, '
                        f'topic={topic}, error={str(e)}'
                    )
                    self.stats['messages_failed'] += 1

                except Exception as e:
                    self.logger.error(
                        f'Subscription handler error: id={subscription_id}, '
                        f'topic={topic}, error={str(e)}',
                        exc_info=True,
                    )
                    self.stats['messages_failed'] += 1

        except asyncio.CancelledError:
            self.logger.info(
                f'Subscription cancelled: id={subscription_id}, topic={topic}'
            )
        except Exception as e:
            self.logger.error(
                f'Subscription error: id={subscription_id}, topic={topic}, '
                f'error={str(e)}',
                exc_info=True,
            )
        finally:
            await consumer.stop()

    task = asyncio.create_task(consume_for_subscription())

    # Store subscription info
    self.subscriptions[subscription_id] = {
        'topic': topic,
        'handler': handler,
        'consumer': consumer,
        'task': task,
    }

    self.logger.info(f'Subscription created: id={subscription_id}, topic={topic}')
    return subscription_id
```

#### Testing Strategy
1. Test subscription handler exception → verify retry
2. Test subscription max retries → verify DLQ
3. Test subscription stats tracking
4. Test multiple subscriptions don't interfere

---

### 5. Add Connection Health Checks

**Severity:** HIGH
**Effort:** Medium

#### Problem
No monitoring of Kafka connection health or automatic recovery:
- Cannot detect when Kafka broker goes down
- No reconnection logic when connection is lost
- Services continue running with broken Kafka connection

#### Proposed Solution

```python
# File: libs/core/src/core/kafka/kafka_pubsub.py

class KafkaPubSubService(AbstractService, IPubSubService):
    def __init__(self):
        # ... existing initialization
        self.health_status = 'unknown'  # unknown, healthy, degraded, down
        self.last_health_check = None
        self.health_check_task: Optional[asyncio.Task] = None
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10

    async def start(self) -> None:
        """Start with health monitoring."""
        await self.start_producer()

        if self.config.CONSUMER_ENABLE:
            await self.start_consumer()

        # ✅ ADD: Start health check loop
        if self.config.KAFKA_HEALTH_CHECK_ENABLE:
            self.health_check_task = asyncio.create_task(self._health_check_loop())

    async def stop(self) -> None:
        """Stop with health check cleanup."""
        self.running = False

        # ✅ ADD: Stop health check task
        if self.health_check_task and not self.health_check_task.done():
            self.health_check_task.cancel()
            try:
                await self.health_check_task
            except asyncio.CancelledError:
                pass

        # ... rest of existing stop logic

    async def _health_check_loop(self) -> None:
        """Periodically check Kafka connection health."""
        self.logger.info('Starting Kafka health check loop')

        while self.running:
            try:
                await self._perform_health_check()
                await asyncio.sleep(self.config.KAFKA_HEALTH_CHECK_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                self.logger.info('Health check loop cancelled')
                break
            except Exception as e:
                self.logger.error(
                    f'Health check loop error: {str(e)}',
                    exc_info=True
                )
                await asyncio.sleep(5)  # Brief pause before retry

    async def _perform_health_check(self) -> None:
        """Perform a single health check."""
        try:
            if not self.admin_client:
                self.health_status = 'down'
                return

            # Ping Kafka by listing topics (lightweight operation)
            start_time = time.time()
            await asyncio.wait_for(
                self.admin_client.list_topics(),
                timeout=5.0  # 5 second timeout
            )
            latency_ms = (time.time() - start_time) * 1000

            # Update health status
            if latency_ms < 1000:  # < 1 second = healthy
                if self.health_status != 'healthy':
                    self.logger.info(
                        f'Kafka connection restored (latency: {latency_ms:.2f}ms)'
                    )
                self.health_status = 'healthy'
                self.reconnect_attempts = 0
            else:  # 1-5 seconds = degraded
                self.health_status = 'degraded'
                self.logger.warning(
                    f'Kafka connection degraded (latency: {latency_ms:.2f}ms)'
                )

            self.last_health_check = datetime.now()

        except asyncio.TimeoutError:
            self.logger.error('Kafka health check timeout')
            self.health_status = 'down'
            await self._attempt_reconnect()

        except Exception as e:
            self.logger.error(
                f'Kafka health check failed: {str(e)}',
                exc_info=True
            )
            self.health_status = 'down'
            await self._attempt_reconnect()

    async def _attempt_reconnect(self) -> None:
        """Attempt to reconnect to Kafka."""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            self.logger.critical(
                f'Max reconnect attempts ({self.max_reconnect_attempts}) reached. '
                'Manual intervention required.'
            )
            return

        self.reconnect_attempts += 1
        self.logger.warning(
            f'Attempting to reconnect to Kafka '
            f'(attempt {self.reconnect_attempts}/{self.max_reconnect_attempts})'
        )

        try:
            # Stop existing clients
            if self.producer:
                await self.producer.stop()
            if self.consumer:
                await self.consumer.stop()
            if self.admin_client:
                await self.admin_client.close()

            # Wait with exponential backoff
            wait_seconds = min(2 ** self.reconnect_attempts, 60)
            self.logger.info(f'Waiting {wait_seconds}s before reconnect...')
            await asyncio.sleep(wait_seconds)

            # Restart clients
            await self.start_producer()
            if self.config.CONSUMER_ENABLE:
                await self.start_consumer()

            self.logger.info('Kafka reconnection successful')
            self.health_status = 'healthy'
            self.reconnect_attempts = 0

        except Exception as e:
            self.logger.error(
                f'Reconnection attempt failed: {str(e)}',
                exc_info=True
            )

    def get_health_status(self) -> dict:
        """Get detailed health status."""
        return {
            'status': self.health_status,
            'last_check': self.last_health_check.isoformat() if self.last_health_check else None,
            'reconnect_attempts': self.reconnect_attempts,
            'producer_running': self.producer is not None,
            'consumer_running': self.consumer is not None,
            'stats': self.get_stats(),
        }
```

**Add Configuration:**

```python
# File: libs/core/src/core/conf/settings.py

class AppSettings(BaseSettings):
    # ... existing settings

    # Health check settings
    KAFKA_HEALTH_CHECK_ENABLE: bool = Field(
        default=True,
        description='Enable Kafka connection health checks'
    )
    KAFKA_HEALTH_CHECK_INTERVAL_SECONDS: int = Field(
        default=30,
        description='Interval between health checks'
    )
```

#### Testing Strategy
1. Test healthy connection → verify status = 'healthy'
2. Test Kafka down → verify status = 'down' and reconnect triggered
3. Test reconnection success
4. Test max reconnect attempts reached
5. Load test: verify health checks don't impact performance

---

### 6. Add Backpressure Handling

**File:** `libs/core/src/core/kafka/kafka_pubsub.py`
**Lines:** 253-270
**Severity:** MEDIUM-HIGH

#### Problem
Current implementation waits when `MAX_CONCURRENT_TASKS` is reached, but doesn't pause the Kafka consumer:

```python
while len(self.processing_tasks) >= self.config.MAX_CONCURRENT_TASKS:
    # ❌ Consumer keeps fetching messages into memory buffer
    done, self.processing_tasks = await asyncio.wait(...)
```

**Consequences:**
- Memory exhaustion with high-throughput topics
- Consumer lag increases
- Potential OOM errors

#### Proposed Solution

```python
async def start_consuming(self) -> None:
    """
    Start the main message consumption loop with backpressure control.
    """
    if not self.consumer:
        raise RuntimeError('Consumer not initialized. Call start_consumer() first.')

    self.logger.info('🔄 Starting message consumption loop (thread-pool)')

    try:
        async for message in self.consumer:
            if not self.running:
                break

            # ✅ FIX: Implement backpressure with consumer pause/resume
            if len(self.processing_tasks) >= self.config.MAX_CONCURRENT_TASKS:
                # Pause consumer to stop fetching new messages
                partitions = self.consumer.assignment()
                if partitions:
                    self.consumer.pause(*partitions)
                    self.logger.warning(
                        f'Backpressure: Consumer paused '
                        f'(active_tasks={len(self.processing_tasks)}, '
                        f'max={self.config.MAX_CONCURRENT_TASKS})'
                    )

                # Wait for at least one task to complete
                done, self.processing_tasks = await asyncio.wait(
                    self.processing_tasks,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                # Clean up completed tasks
                for task in done:
                    try:
                        await task
                    except Exception as e:
                        self.logger.error(
                            f'Task failed: {str(e)}',
                            exc_info=True,
                        )

                # Resume consumer
                if partitions:
                    self.consumer.resume(*partitions)
                    self.logger.debug(
                        f'Backpressure: Consumer resumed '
                        f'(active_tasks={len(self.processing_tasks)})'
                    )

            # Create task for message processing
            task = asyncio.create_task(self._process_message(message))
            self.processing_tasks.add(task)
            task.add_done_callback(self.processing_tasks.discard)

    except Exception as e:
        self.logger.error(
            f'Error in consumption loop: {str(e)}',
            exc_info=True,
        )
        raise
```

#### Advanced: Adaptive Backpressure

For production systems, consider adaptive thresholds:

```python
class AdaptiveBackpressure:
    """Dynamically adjust concurrency based on system load."""

    def __init__(self, min_tasks=10, max_tasks=100, target_latency_ms=1000):
        self.min_tasks = min_tasks
        self.max_tasks = max_tasks
        self.current_limit = min_tasks
        self.target_latency_ms = target_latency_ms
        self.recent_latencies = []

    def should_pause(self, active_tasks: int) -> bool:
        return active_tasks >= self.current_limit

    def adjust(self, avg_latency_ms: float):
        """Adjust concurrency limit based on processing latency."""
        if avg_latency_ms < self.target_latency_ms * 0.8:
            # Performing well, increase concurrency
            self.current_limit = min(self.current_limit + 5, self.max_tasks)
        elif avg_latency_ms > self.target_latency_ms * 1.2:
            # Struggling, decrease concurrency
            self.current_limit = max(self.current_limit - 5, self.min_tasks)
```

#### Testing Strategy
1. High-throughput test: Verify consumer pauses when limit reached
2. Memory test: Monitor memory usage under sustained load
3. Latency test: Verify pause/resume doesn't add excessive latency
4. Integration test: Verify no message loss during pause/resume

---

## 🔧 Code Quality Improvements

### 7. Remove Commented-Out Code

**Files:**
- `libs/core/src/core/common/event_processor.py` (lines 95-106)
- `libs/core/src/core/kafka/kafka_pubsub.py` (lines 36-39)

**Action:** Remove all commented-out code after fixing trace context propagation.

---

### 8. Consolidate Consumption Methods

**Problem:** Two consumption methods causing confusion:
- `start_consuming()` - concurrent
- `start_consuming_sequential()` - sequential

**Recommendation:**
1. Remove `start_consuming_sequential()` to avoid confusion
2. OR add configuration flag:

```python
async def start_consuming(self) -> None:
    """Start consumption based on configuration."""
    if self.config.KAFKA_CONCURRENT_PROCESSING:
        await self._consume_concurrent()
    else:
        await self._consume_sequential()
```

---

### 9. Add Configuration Validation

**File:** `libs/core/src/core/kafka/kafka_pubsub.py`

```python
def __init__(self):
    # ... existing initialization

    # ✅ ADD: Validate configuration
    self._validate_config()

def _validate_config(self) -> None:
    """Validate configuration values."""
    if self.config.MAX_RETRIES < 1:
        raise ValueError(
            f'MAX_RETRIES must be >= 1, got {self.config.MAX_RETRIES}'
        )

    if self.config.MAX_CONCURRENT_TASKS < 1:
        raise ValueError(
            f'MAX_CONCURRENT_TASKS must be >= 1, '
            f'got {self.config.MAX_CONCURRENT_TASKS}'
        )

    if self.config.RETRY_BACKOFF_MS < 0:
        raise ValueError(
            f'RETRY_BACKOFF_MS must be >= 0, '
            f'got {self.config.RETRY_BACKOFF_MS}'
        )

    if self.config.GRACEFUL_SHUTDOWN_TIMEOUT < 0:
        raise ValueError(
            f'GRACEFUL_SHUTDOWN_TIMEOUT must be >= 0, '
            f'got {self.config.GRACEFUL_SHUTDOWN_TIMEOUT}'
        )

    if not self.config.kafka_bootstrap_servers_list:
        raise ValueError('kafka_bootstrap_servers_list cannot be empty')
```

---

### 10. Fix Magic Numbers

**Replace magic numbers with configuration:**

```python
# In event_processor.py
wait=wait_exponential(
    multiplier=1,
    min=self.config.RETRY_BACKOFF_MS / 1000,
    max=60,  # ❌ Magic number
)

# Should be:
wait=wait_exponential(
    multiplier=1,
    min=self.config.RETRY_BACKOFF_MS / 1000,
    max=self.config.RETRY_MAX_BACKOFF_SECONDS,
)
```

**Add to settings:**

```python
RETRY_MAX_BACKOFF_SECONDS: int = Field(
    default=60,
    description='Maximum backoff delay between retries'
)
```

---

### 11. Improve Commit Strategy

**Problem:** Committing after every message has high overhead

```python
# Current (line 360)
if not self.config.KAFKA_ENABLE_AUTO_COMMIT:
    await self.consumer.commit()  # ❌ Every message
```

**Recommendation: Batch commits**

```python
def __init__(self):
    # ... existing initialization
    self.processed_count = 0

async def _process_message(self, message: ConsumerRecord) -> None:
    # ... existing processing logic

    if result.success:
        self.stats['messages_processed'] += 1
        self.processed_count += 1

        # ✅ Batch commits every N messages
        if not self.config.KAFKA_ENABLE_AUTO_COMMIT:
            if self.processed_count % self.config.COMMIT_BATCH_SIZE == 0:
                await self.consumer.commit()
                self.logger.debug(
                    f'Committed offset (batch size: {self.config.COMMIT_BATCH_SIZE})'
                )
```

**Add configuration:**

```python
COMMIT_BATCH_SIZE: int = Field(
    default=10,
    description='Number of messages to process before committing offset'
)
```

---

### 12. Add Message Size Limits

**Prevent large messages from causing issues:**

```python
async def publish(self, topic: str, message: BaseEvent) -> None:
    """Publish with size validation."""
    if not self.producer:
        raise RuntimeError('Producer not initialized. Call start() first.')

    # Serialize message
    message_dict = message.model_dump(mode='json')
    message_bytes = json.dumps(message_dict).encode('utf-8')

    # ✅ ADD: Validate message size
    message_size = len(message_bytes)
    if message_size > self.config.MAX_MESSAGE_SIZE_BYTES:
        raise ValueError(
            f'Message exceeds max size: {message_size} bytes > '
            f'{self.config.MAX_MESSAGE_SIZE_BYTES} bytes '
            f'(event_id={message.metadata.event_id})'
        )

    self.logger.debug(
        f'Publishing message: topic={topic}, '
        f'event_id={message.metadata.event_id}, '
        f'size={message_size} bytes'
    )

    # ... rest of publish logic
```

**Add configuration:**

```python
MAX_MESSAGE_SIZE_BYTES: int = Field(
    default=1024 * 1024,  # 1MB
    description='Maximum message size in bytes'
)
```

---

### 13. Add Null Safety Check in _process_message

**Current:** Only in `subscribe()` method

```python
# In subscribe() - line 556
if message.value is None:
    continue  # ✅ Good
```

**Missing in:** `_process_message()`

**Fix:**

```python
async def _process_message(self, message: ConsumerRecord) -> None:
    """Process a single Kafka message."""

    # ✅ ADD: Null check at the start
    if message.value is None:
        self.logger.warning(
            f'Received null message: topic={message.topic}, '
            f'partition={message.partition}, offset={message.offset}'
        )
        return

    # Extract trace context from headers
    traceparent: str | None = None
    # ... rest of existing code
```

---

### 14. Add Circuit Breaker for DLQ

**Prevent infinite retry loops if DLQ is down:**

```python
class CircuitBreaker:
    """Simple circuit breaker for DLQ operations."""

    def __init__(self, failure_threshold=10, timeout_seconds=60):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.timeout_seconds = timeout_seconds
        self.circuit_open = False
        self.circuit_opened_at = None

    def record_success(self):
        self.failure_count = 0
        self.circuit_open = False

    def record_failure(self):
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            self.circuit_open = True
            self.circuit_opened_at = time.time()

    def is_open(self) -> bool:
        if not self.circuit_open:
            return False

        # Auto-close after timeout
        if time.time() - self.circuit_opened_at > self.timeout_seconds:
            self.circuit_open = False
            self.failure_count = 0
            return False

        return True


# In KafkaPubSubService.__init__:
self.dlq_circuit_breaker = CircuitBreaker()

# In _send_to_dlq:
async def _send_to_dlq(...):
    # ✅ ADD: Check circuit breaker
    if self.dlq_circuit_breaker.is_open():
        self.logger.critical(
            f'DLQ circuit breaker OPEN - cannot send to DLQ: '
            f'event_id={event.metadata.event_id}'
        )
        # Log to file or alert instead
        return

    try:
        # ... existing DLQ send logic

        # ✅ Record success
        self.dlq_circuit_breaker.record_success()

    except Exception as e:
        # ✅ Record failure
        self.dlq_circuit_breaker.record_failure()

        if self.dlq_circuit_breaker.is_open():
            self.logger.critical('DLQ circuit breaker OPENED!')

        raise
```

---

## 📊 Monitoring & Observability Improvements

### 15. Add Metrics Export

**Create metrics endpoint for Prometheus/DataDog:**

```python
# File: libs/core/src/core/kafka/metrics.py

class KafkaMetrics:
    """Kafka metrics for monitoring."""

    def __init__(self, kafka_service: KafkaPubSubService):
        self.kafka_service = kafka_service

    async def get_consumer_lag(self) -> dict:
        """Calculate consumer lag per partition."""
        if not self.kafka_service.consumer:
            return {}

        lag_by_partition = {}
        for partition in self.kafka_service.consumer.assignment():
            position = await self.kafka_service.consumer.position(partition)
            high_water_mark = await self.kafka_service.consumer.highwater(partition)
            lag = high_water_mark - position

            lag_by_partition[f'{partition.topic}:{partition.partition}'] = {
                'position': position,
                'high_water_mark': high_water_mark,
                'lag': lag,
            }

        return lag_by_partition

    def get_prometheus_metrics(self) -> str:
        """Export metrics in Prometheus format."""
        stats = self.kafka_service.get_stats()

        metrics = [
            f'kafka_messages_processed_total {stats["messages_processed"]}',
            f'kafka_messages_failed_total {stats["messages_failed"]}',
            f'kafka_messages_retried_total {stats["messages_retried"]}',
            f'kafka_messages_dlq_total {stats["messages_dlq"]}',
            f'kafka_messages_published_total {stats["messages_published"]}',
            f'kafka_active_tasks {stats["active_tasks"]}',
            f'kafka_active_subscriptions {stats["active_subscriptions"]}',
            f'kafka_running {1 if stats["running"] else 0}',
        ]

        return '\n'.join(metrics)
```

---

### 16. Add Distributed Tracing Attributes

**Enhance span attributes for better observability:**

```python
# In EventProcessor.process_event:
with ContextTracer(handler_name, traceparent, context=trace_context) as span:
    # ✅ ADD: More detailed attributes
    span.set_attribute('handler_name', handler_name)
    span.set_attribute('event_id', event.metadata.event_id)
    span.set_attribute('event_type', event.metadata.event_type)
    span.set_attribute('retry_count', event.metadata.retry_count)

    # ✅ ADD: Business context
    if event.metadata.user_id:
        span.set_attribute('user_id', event.metadata.user_id)
    if event.metadata.source:
        span.set_attribute('event_source', event.metadata.source)
    if event.metadata.correlation_id:
        span.set_attribute('correlation_id', event.metadata.correlation_id)

    # ✅ ADD: Payload size
    payload_size = len(json.dumps(event.payload))
    span.set_attribute('payload_size_bytes', payload_size)

    # ... processing logic
```

---

## 🧪 Testing Improvements

### 17. Add Integration Tests

**Missing test scenarios:**

1. **Retry Mechanism Tests:**
```python
async def test_retry_count_accuracy():
    """Verify retry count increments correctly."""
    # Handler that fails 2 times then succeeds
    # Assert retry_count == 2 after success

async def test_max_retries_triggers_dlq():
    """Verify DLQ triggered after MAX_RETRIES."""
    # Handler that always fails
    # Assert event sent to DLQ after MAX_RETRIES
```

2. **Trace Propagation Tests:**
```python
async def test_trace_context_propagation():
    """Verify trace context flows through Kafka."""
    # Publish with active span
    # Consume and verify child span created
    # Assert parent-child relationship
```

3. **Idempotency Tests:**
```python
async def test_duplicate_message_handling():
    """Verify duplicate messages only processed once."""
    # Publish same event twice
    # Assert handler called only once
    # Assert idempotency cache contains event_id
```

4. **Backpressure Tests:**
```python
async def test_consumer_pauses_under_load():
    """Verify consumer pauses when task limit reached."""
    # Publish 1000 messages rapidly
    # Assert consumer pauses
    # Assert memory doesn't grow unbounded
```

---

## 📅 Implementation Roadmap

### Phase 1: Critical Fixes (Week 1-2)
- [ ] Fix retry mechanism double-counting
- [ ] Fix trace context propagation
- [ ] Add null safety check in `_process_message`
- [ ] Remove commented-out code
- [ ] Add configuration validation
- [ ] Write unit tests for fixes

### Phase 2: High Priority (Week 3-4)
- [ ] Implement idempotency handling
- [ ] Improve error handling in `subscribe()`
- [ ] Add connection health checks
- [ ] Add backpressure handling
- [ ] Write integration tests

### Phase 3: Code Quality (Week 5-6)
- [ ] Consolidate consumption methods
- [ ] Fix magic numbers
- [ ] Improve commit strategy
- [ ] Add message size limits
- [ ] Add circuit breaker for DLQ
- [ ] Code review and cleanup

### Phase 4: Observability (Week 7-8)
- [ ] Add metrics export
- [ ] Enhance distributed tracing
- [ ] Add performance monitoring
- [ ] Load testing
- [ ] Documentation updates

---

## 🎯 Success Metrics

### Before (Current State)
- ❌ Retry count inaccurate
- ❌ Distributed tracing broken
- ❌ No idempotency protection
- ⚠️ Memory growth under high load
- ⚠️ No connection health monitoring

### After (Target State)
- ✅ 100% accurate retry counts
- ✅ Full distributed tracing support
- ✅ Zero duplicate processing (with idempotency)
- ✅ Stable memory usage under load
- ✅ Automatic reconnection on failure
- ✅ 99.9% message delivery reliability
- ✅ < 50ms p99 processing latency

### Monitoring KPIs
- Message processing rate (msg/sec)
- Consumer lag (messages behind)
- Error rate (errors/sec)
- DLQ rate (msg to DLQ/sec)
- Retry rate (retries/message)
- Processing latency (p50, p95, p99)
- Memory usage (MB)
- Connection health (uptime %)

---

## 📚 References

### Documentation
- [Apache Kafka Best Practices](https://kafka.apache.org/documentation/)
- [aiokafka Documentation](https://aiokafka.readthedocs.io/)
- [OpenTelemetry Python](https://opentelemetry.io/docs/instrumentation/python/)
- [Tenacity Retry Library](https://tenacity.readthedocs.io/)

### Related Files
- `/libs/core/src/core/kafka/kafka_pubsub.py` - Main Kafka service
- `/libs/core/src/core/common/event_processor.py` - Event processing logic
- `/libs/core/src/core/common/event_handler.py` - Handler registry
- `/libs/core/tests/kafka/` - Test suite

### Configuration Files
- `/config/base.toml` - Base configuration
- `/libs/core/src/core/conf/settings.py` - Settings schema

---

## 🤝 Contributors

Review and implementation tracking:
- [ ] Code review completed
- [ ] Architecture review completed
- [ ] Security review completed
- [ ] Performance testing completed
- [ ] Documentation updated
- [ ] Team training completed

---

**Last Updated:** January 17, 2026
**Next Review:** After Phase 1 completion
