# EVENT_PROCESSOR_FAST_DIAGRAM

```pre
┌─────────────────────────────────────────────────────────────────────┐
│                       EventProcessorFast                            │
│  Centralized event processing with retry, observability & DLQ      │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              │ Configuration
                              ▼
                    ┌──────────────────┐
                    │  EventProcessor  │
                    │     Config       │
                    ├──────────────────┤
                    │ • retry_enabled  │
                    │ • max_retries    │
                    │ • enable_dlq     │
                    │ • parallel_exec  │
                    │ • max_concurrent │
                    └──────────────────┘
                              │
            ┌─────────────────┼─────────────────┐
            │                 │                 │
            ▼                 ▼                 ▼
    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
    │Handler       │  │Retry Policy  │  │DLQ Service   │
    │Registry      │  │(Tenacity)    │  │(Database)    │
    └──────────────┘  └──────────────┘  └──────────────┘

════════════════════════════════════════════════════════════════════
                     PROCESSING FLOW
════════════════════════════════════════════════════════════════════

Mode 1: SEQUENTIAL (default)
────────────────────────────────
  Event → process_event() → Handler → Success ✓
                              │
                              │ Fail
                              ▼
                           Retry (with backoff)
                              │
                              ├─ Success ✓
                              │
                              └─ Max retries → DLQ → Database


Mode 2: PARALLEL (enable_parallel_execution=true)
──────────────────────────────────────────────────
  Events Batch → process_events_batch()
                         │
                         ▼
            ┌────────────────────────┐
            │  Task Pool Manager     │
            │  (max_concurrent_tasks)│
            └────────────────────────┘
                    │   │   │
         ┌──────────┼───┼───┼──────────┐
         ▼          ▼   ▼   ▼          ▼
      Task-1    Task-2 ... Task-N  (throttled)
         │          │       │
         ▼          ▼       ▼
      Handler    Handler  Handler
         │          │       │
         └──────────┴───────┘
                    │
                    ▼
            Results (ordered)


════════════════════════════════════════════════════════════════════
                   DETAILED EVENT FLOW
════════════════════════════════════════════════════════════════════

┌─────────────┐
│   Event     │
│   arrives   │
└──────┬──────┘
       │
       ▼
┌──────────────────────────────┐
│ 1. Lookup Handler            │
│    - handlerRegistry         │
│    - by event_type           │
└──────┬───────────────────────┘
       │
       ▼
┌──────────────────────────────┐
│ 2. Execute with Tracing      │
│    - Create OTel span        │
│    - Propagate traceparent   │
│    - Record metrics          │
└──────┬───────────────────────┘
       │
       ▼
┌──────────────────────────────┐
│ 3. Retry Logic (if enabled)  │
│    - Exponential backoff     │
│    - Increment retry_count   │
│    - Track stats             │
└──────┬───────────────────────┘
       │
       ├──── Success ────────────────┐
       │                             │
       └──── Failure ────────────────┤
              │                       │
              ▼                       ▼
       ┌─────────────┐         ┌──────────┐
       │ Retry < Max?│         │ Success  │
       └──────┬──────┘         │ Result   │
              │                └──────────┘
       ┌──────┴──────┐
       │             │
      Yes           No
       │             │
       └─(loop)      ▼
              ┌──────────────┐
              │ Save to DLQ  │
              │  (if enabled)│
              └──────┬───────┘
                     │
                     ▼
              ┌──────────────┐
              │  Database    │
              │  dlq_events  │
              └──────────────┘


════════════════════════════════════════════════════════════════════
                   COMPONENTS
════════════════════════════════════════════════════════════════════

┌────────────────────────────────────────────────────────────────┐
│ EventProcessorFast                                             │
├────────────────────────────────────────────────────────────────┤
│ Fields:                                                        │
│  • config: EventProcessorConfig                                │
│  • retry_policy: TenacityRetry                                 │
│  • processing_tasks: Set[asyncio.Task]                         │
│  • session_factory: Callable → AsyncSession                    │
│  • dlq_service: DLQService | None                              │
│  • stats: Dict (retries, dlq, active_tasks)                    │
│                                                                │
│ Methods:                                                       │
│  • process_event(event) → ProcessingResult                     │
│  • process_events_batch([events]) → [ProcessingResult]         │
│  • cleanup() → None                                            │
│  • _save_to_dlq(event, result) → None                          │
│  • get_stats() → Dict                                          │
└────────────────────────────────────────────────────────────────┘


════════════════════════════════════════════════════════════════════
               METRICS & OBSERVABILITY
════════════════════════════════════════════════════════════════════

Stats Tracked:
  ├─ messages_retried     (retry counter)
  ├─ messages_dlq         (DLQ saves)
  └─ active_tasks         (parallel tasks count)

OpenTelemetry:
  ├─ Span creation per event
  ├─ Exception recording
  ├─ Trace context propagation
  └─ Handler timing

Logs:
  ├─ INFO: Success/retry attempts
  ├─ WARNING: DLQ saves, no handler
  └─ ERROR: Failed handlers, DLQ errors


════════════════════════════════════════════════════════════════════
                  USAGE PATTERNS
════════════════════════════════════════════════════════════════════

# Basic (Sequential + Retry + DLQ)
processor = EventProcessorFast(session_factory=db.session_factory())
result = await processor.process_event(event)

# High-throughput (Parallel)
config = EventProcessorConfig(
    enable_parallel_execution=True,
    max_concurrent_tasks=50
)
processor = EventProcessorFast(config=config)
results = await processor.process_events_batch(events)

# Cleanup on shutdown
await processor.cleanup()
```
