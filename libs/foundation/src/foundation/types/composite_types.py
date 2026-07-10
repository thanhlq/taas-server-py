from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Iterator,
    Literal,
    Mapping,
    Sequence,
    Tuple,
    Type,
    TypeAlias,
    Union,
)

if TYPE_CHECKING:

    from typing_extensions import TypeAlias

    from foundation.enums import ScopeType
    from foundation.middleware.base import DefineMiddleware, MiddlewareProtocol

    from .asgi_types import ASGIApp

from foundation.enums import ScopeType

# Dependencies: TypeAlias = "Mapping[str, Union[Provide, AnyCallable]]"  # noqa: UP007
# ExceptionHandlersMap: TypeAlias = "MutableMapping[Union[int, Type[Exception]], ExceptionHandler]"  # noqa: UP007
# Middleware: TypeAlias = "Union[Callable[..., ASGIApp], DefineMiddleware, Iterator[Tuple[ASGIApp, Dict[str, Any]]], Type[MiddlewareProtocol]]"  # noqa: UP007
# ParametersMap: TypeAlias = "Mapping[str, ParameterKwarg]"
# PathType: TypeAlias = "Union[Path, PathLike, str]"  # noqa: UP007
# ResponseCookies: TypeAlias = "Union[Sequence[Cookie], Mapping[str, str]]"  # noqa: UP007
# ResponseHeaders: TypeAlias = "Union[Sequence[ResponseHeader], Mapping[str, str]]"  # noqa: UP007
# Scopes: TypeAlias = "set[Literal[ScopeType.HTTP, ScopeType.WEBSOCKET]]"
TypeDecodersSequence: TypeAlias = (
    'Sequence[tuple[Callable[[Any], bool], Callable[[Any, Any], Any]]]'
)
TypeEncodersMap: TypeAlias = 'Mapping[Any, Callable[[Any], Any]]'
Scopes: TypeAlias = 'set[Literal[ScopeType.HTTP, ScopeType.WEBSOCKET]]'
Middleware: TypeAlias = 'Union[Callable[..., ASGIApp], DefineMiddleware, Iterator[Tuple[ASGIApp, Dict[str, Any]]], Type[MiddlewareProtocol]]'  # noqa: UP007
