"""Default :class:`Litestar` factory used by :mod:`ews_api` and similar
applications. Mirrors :mod:`http_fastapi.base_fastapi_app` so callers can
swap frameworks without touching their setup code."""
from __future__ import annotations

from typing import Any

from litestar import Litestar, get


@get("/hello", sync_to_thread=False)
def _hello() -> dict[str, str]:
    return {"message": "Hello from Litestar!"}


def build_app(**kwargs: Any) -> Litestar:
    """Construct a baseline :class:`Litestar` application.

    Extra ``route_handlers`` passed via ``kwargs`` are prepended to the
    default ones, matching the FastAPI counterpart's behaviour of letting
    callers extend the baseline app.
    """
    handlers = list(kwargs.pop("route_handlers", []) or [])
    handlers.append(_hello)
    return Litestar(route_handlers=handlers, **kwargs)
