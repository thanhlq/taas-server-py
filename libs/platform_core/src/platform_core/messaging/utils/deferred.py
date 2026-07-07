# libs/core/src/core/messaging/deferred.py
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import List


@dataclass
class DeferredEmit:
    topic: str
    payload: dict
    key: str | None = None


_collector: ContextVar[List[DeferredEmit] | None] = ContextVar(
    'deferred_emit_collector', default=None
)


def open_deferred_context() -> list[DeferredEmit]:
    """Call at the start of processing one event. Returns the collector list."""
    collector: List[DeferredEmit] = []
    _collector.set(collector)
    return collector


def close_deferred_context() -> None:
    _collector.set(None)


def stage_deferred(topic: str, payload: dict, key: str | None = None) -> None:
    """
    Called by handlers instead of messaging_service.send().
    Thread/task-safe via ContextVar — each asyncio task has its own value.
    """
    collector = _collector.get()
    if collector is None:
        raise RuntimeError(
            'stage_deferred() called outside an open deferred context. '
            'Ensure EventProcessor.process() opened one.'
        )
    collector.append(DeferredEmit(topic=topic, payload=payload, key=key))
