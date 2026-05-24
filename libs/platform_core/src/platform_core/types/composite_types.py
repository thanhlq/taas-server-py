from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Iterator,
    Literal,
    Mapping,
    MutableMapping,
    Sequence,
    Tuple,
    Type,
    TypeAlias,
    Union,
)

if TYPE_CHECKING:
    from os import PathLike
    from pathlib import Path

    from typing_extensions import TypeAlias

    from platform_core.datastructures.response_header import ResponseHeader
    from platform_core.enums import ScopeType
    from platform_core.middleware.base import DefineMiddleware, MiddlewareProtocol
    from platform_core.params import ParameterKwarg

    from .asgi_types import ASGIApp
    from .callable_types import AnyCallable

from platform_core.enums import ScopeType

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
