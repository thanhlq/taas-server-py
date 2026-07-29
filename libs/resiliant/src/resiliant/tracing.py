"""
Resilience trace attributes.

Small helper to stamp saga / event / step identifiers onto the *current*
OpenTelemetry span so a stuck flow is one trace-search away — the pattern-stack
substitute for Temporal's per-workflow event history. Call it from an event
handler or the messaging ``EventProcessor``::

    set_resilience_attributes(saga_id=saga.id, saga_step=saga.current_step,
                              event_id=event.event_id)

It is defensive by design: OpenTelemetry is imported lazily and any failure
(no active span, otel absent) is swallowed — tracing must never break business
logic.
"""

from __future__ import annotations

from typing import Any

_ATTR_PREFIX = 'resiliant.'


def set_resilience_attributes(**attributes: Any) -> None:
    """Set ``resiliant.<key>`` attributes on the active span (best effort)."""
    if not attributes:
        return
    try:
        from opentelemetry import trace  # type: ignore

        span = trace.get_current_span()
        if span is None or not span.is_recording():
            return
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(f'{_ATTR_PREFIX}{key}', str(value))
    except Exception:  # noqa: BLE001 - observability must never raise
        return


__all__ = ['set_resilience_attributes']
