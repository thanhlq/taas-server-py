from __future__ import annotations

import abc
import warnings
from abc import abstractmethod
from typing import TYPE_CHECKING, Any, Callable, Protocol, runtime_checkable

from platform_core.types import ASGIApp, Scope
from platform_core.types.asgi_types import Receive, Send


@runtime_checkable
class MiddlewareProtocol(Protocol):
    """Abstract middleware protocol."""

    __slots__ = ('app',)

    app: ASGIApp

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Execute the ASGI middleware.

        Called by the previous middleware in the stack if a response is not awaited prior.

        Upon completion, middleware should call the next ASGI handler and await it - or await a response created in its
        closure.

        Args:
            scope: The ASGI connection scope.
            receive: The ASGI receive function.
            send: The ASGI send function.

        Returns:
            None
        """


class DefineMiddleware:
    """Container enabling passing ``*args`` and ``**kwargs`` to Middleware class constructors and factory functions."""

    __slots__ = ('args', 'kwargs', 'middleware')

    def __init__(
        self, middleware: Callable[..., ASGIApp], *args: Any, **kwargs: Any
    ) -> None:
        """Initialize ``DefineMiddleware``.

        Args:
            middleware: A callable that returns an ASGIApp.
            *args: Positional arguments to pass to the callable.
            **kwargs: Key word arguments to pass to the callable.

        Notes:
            The callable will be passed a kwarg ``app``, which is the next ASGI app to call in the middleware stack.
            It therefore must define such a kwarg.
        """
        self.middleware = middleware
        self.args = args
        self.kwargs = kwargs

    def __call__(self, app: ASGIApp) -> ASGIApp:
        """Call the middleware constructor or factory.

        Args:
            app: An ASGIApp, this value is the next ASGI handler to call in the middleware stack.

        Returns:
            Calls :class:`DefineMiddleware.middleware <.DefineMiddleware>` and returns the ASGIApp created.
        """

        return self.middleware(*self.args, app=app, **self.kwargs)
