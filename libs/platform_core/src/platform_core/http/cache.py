"""Framework-agnostic response cache decorator.

This decorator caches the result of an async endpoint function. It works with
any web framework (FastAPI, Litestar, ...) as long as the endpoint exposes a
``request`` parameter (any object with ``.method`` and ``.headers``) and
optionally a ``response`` parameter (any object with ``.headers`` and
``.status_code``).

Storage is delegated to the platform :class:`ICacheService` resolved via
:func:`get_cache_service`. Values are serialized with
:func:`platform_core.serialization.encode_json` / :func:`decode_json`.
"""
from __future__ import annotations

import hashlib
import inspect
import logging
import typing
from functools import wraps
from inspect import Parameter, Signature, iscoroutinefunction
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    ParamSpec,
    Protocol,
    Tuple,
    TypeVar,
    Union,
    cast,
    runtime_checkable,
)

from platform_core.config import get_settings
from platform_core.facade.cache import ICacheService
from platform_core.serialization import decode_json, encode_json
from platform_core.state.service_registry import get_service

logger: logging.Logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

P = ParamSpec("P")
R = TypeVar("R")

HTTP_304_NOT_MODIFIED = 304

_Func = Callable[..., Any]


# ---------------------------------------------------------------------------
# Duck-typed Protocols so we don't depend on any specific web framework.
# ---------------------------------------------------------------------------
@runtime_checkable
class RequestLike(Protocol):
    method: str

    @property
    def headers(self) -> Any: ...  # mapping with case-insensitive .get


@runtime_checkable
class ResponseLike(Protocol):
    status_code: int

    @property
    def headers(self) -> Any: ...  # mutable mapping supporting .update


class KeyBuilder(Protocol):
    def __call__(
        self,
        __function: _Func,
        __namespace: str = ...,
        *,
        request: Optional[RequestLike] = ...,
        response: Optional[ResponseLike] = ...,
        args: Tuple[Any, ...],
        kwargs: Dict[str, Any],
    ) -> Union[Awaitable[str], str]: ...


def get_cache_service() -> ICacheService:
    return get_service(ICacheService)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _augment_signature(signature: Signature, *extra: Parameter) -> Signature:
    if not extra:
        return signature

    parameters = list(signature.parameters.values())
    variadic_keyword_params: List[Parameter] = []
    while parameters and parameters[-1].kind is Parameter.VAR_KEYWORD:
        variadic_keyword_params.append(parameters.pop())

    return signature.replace(parameters=[*parameters, *extra, *variadic_keyword_params])


def _locate_param(
    sig: Signature, dep: Parameter, to_inject: List[Parameter]
) -> Parameter:
    """Locate an existing parameter in the decorated endpoint.

    Match is done by name first (``request`` / ``response``) then by
    annotation identity. If not found, the injectable placeholder is appended
    to ``to_inject`` so callers know to add it to the public signature.
    """
    # 1. exact name match — look for plain ``request`` / ``response`` first
    short = "request" if "request" in dep.name else "response"
    if short in sig.parameters:
        return sig.parameters[short]
    if dep.name in sig.parameters:
        return sig.parameters[dep.name]
    # 2. annotation identity match
    param = next(
        (p for p in sig.parameters.values() if p.annotation is dep.annotation),
        None,
    )
    if param is None:
        to_inject.append(dep)
        param = dep
    return param


def _header_get(headers: Any, name: str) -> Optional[str]:
    """Read a header from a request/response in a framework-agnostic way."""
    if headers is None:
        return None
    getter = getattr(headers, "get", None)
    if getter is None:
        return None
    try:
        return getter(name)
    except Exception:
        return None


def _uncacheable(request: Optional[RequestLike]) -> bool:
    """Determine whether the current request should bypass the cache."""
    settings = get_settings()
    if not settings.app.get_cache_config().enabled:
        return True
    if request is None:
        return False
    if getattr(request, "method", "GET") != "GET":
        return True
    return _header_get(getattr(request, "headers", None), "Cache-Control") == "no-store"


def _default_key_builder(
    func: _Func,
    namespace: str = "",
    *,
    request: Optional[RequestLike] = None,
    response: Optional[ResponseLike] = None,
    args: Tuple[Any, ...] = (),
    kwargs: Optional[Dict[str, Any]] = None,
) -> str:
    kwargs = kwargs or {}
    fn_id = f"{getattr(func, '__module__', '')}.{getattr(func, '__qualname__', getattr(func, '__name__', repr(func)))}"
    payload = f"{fn_id}:{args}:{sorted(kwargs.items())}"
    digest = hashlib.md5(payload.encode("utf-8")).hexdigest()  # noqa: S324  # cache key, not security
    return f"{namespace}:{digest}"


# ---------------------------------------------------------------------------
# Public decorator
# ---------------------------------------------------------------------------
def cache(
    expire: Optional[int] = None,
    key_builder: Optional[KeyBuilder] = None,
    namespace: str = "",
    injected_dependency_namespace: str = "__platform_cache",
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[Union[R, ResponseLike]]]]:
    """Cache the result of an async endpoint.

    Args:
        expire: TTL in seconds. Falls back to ``CacheConfig.ttl`` when omitted.
        key_builder: Optional callable to build the cache key.
        namespace: Logical grouping appended to the configured ``key_prefix``.
        injected_dependency_namespace: Prefix for synthesized request/response
            parameters when the endpoint does not already declare them.
    """

    injected_request = Parameter(
        name="request",
        annotation=RequestLike,
        kind=Parameter.KEYWORD_ONLY,
    )
    injected_response = Parameter(
        name="response",
        annotation=ResponseLike,
        kind=Parameter.KEYWORD_ONLY,
    )

    def wrapper(
        func: Callable[P, Awaitable[R]],
    ) -> Callable[P, Awaitable[Union[R, ResponseLike]]]:
        wrapped_signature = inspect.signature(func)
        to_inject: List[Parameter] = []
        request_param = _locate_param(wrapped_signature, injected_request, to_inject)
        response_param = _locate_param(wrapped_signature, injected_response, to_inject)

        try:
            type_hints = typing.get_type_hints(func)
            return_type: Any = type_hints.get("return", Any)
        except Exception:
            return_type = Any

        @wraps(func)
        async def inner(*args: P.args, **kwargs: P.kwargs) -> Union[R, ResponseLike]:
            nonlocal expire
            nonlocal key_builder

            # Only strip request/response from the forwarded kwargs when WE
            # injected them — if the user already declared those params we
            # must pass them through.
            _strip_request = injected_request in to_inject
            _strip_response = injected_response in to_inject

            async def _call(*a: P.args, **kw: P.kwargs) -> R:
                if _strip_request:
                    kw.pop(request_param.name, None)
                if _strip_response:
                    kw.pop(response_param.name, None)
                if iscoroutinefunction(func):
                    return await func(*a, **kw)
                return cast(R, func(*a, **kw))

            copy_kwargs = kwargs.copy()
            request: Optional[RequestLike] = copy_kwargs.pop(request_param.name, None)  # type: ignore[assignment]
            response: Optional[ResponseLike] = copy_kwargs.pop(response_param.name, None)  # type: ignore[assignment]

            if _uncacheable(request):
                return await _call(*args, **kwargs)

            cache_config = get_settings().app.get_cache_config()
            prefix = cache_config.key_prefix
            expire = expire or cache_config.ttl
            key_builder = key_builder or _default_key_builder

            full_namespace = f"{prefix}:{namespace}" if namespace else prefix
            cache_key = key_builder(
                func,
                full_namespace,
                request=request,
                response=response,
                args=args,
                kwargs=copy_kwargs,
            )
            if inspect.isawaitable(cache_key):
                cache_key = await cache_key
            assert isinstance(cache_key, str)  # noqa: S101

            backend = get_cache_service()
            cached: Optional[bytes] = None
            ttl: Optional[int] = None
            try:
                cached = await backend.get(cache_key)
                if cached is not None:
                    ttl = await backend.expires_in(cache_key)
            except Exception:
                logger.warning(
                    "Error retrieving cache key '%s' from backend", cache_key, exc_info=True
                )
                cached = None
                ttl = None

            force_refresh = (
                request is not None
                and _header_get(getattr(request, "headers", None), "Cache-Control")
                == "no-cache"
            )

            if cached is None or force_refresh:  # cache miss
                result = await _call(*args, **kwargs)
                try:
                    to_cache = encode_json(result)
                except Exception:
                    logger.warning(
                        "Error encoding result for cache key '%s'", cache_key, exc_info=True
                    )
                    to_cache = None

                if to_cache is not None:
                    try:
                        await backend.set(cache_key, to_cache, expires_in=expire)
                    except Exception:
                        logger.warning(
                            "Error setting cache key '%s' in backend", cache_key, exc_info=True
                        )

                if response is not None and to_cache is not None:
                    try:
                        response.headers.update(
                            {
                                "Cache-Control": f"max-age={expire}",
                                "ETag": f'W/"{hash(to_cache)}"',
                                "X-Cache": "MISS",
                            }
                        )
                    except Exception:
                        logger.debug("Failed to set MISS response headers", exc_info=True)
                return result

            # cache hit
            etag = f'W/"{hash(cached)}"'
            if response is not None:
                try:
                    response.headers.update(
                        {
                            "Cache-Control": f"max-age={ttl if ttl is not None else expire}",
                            "ETag": etag,
                            "X-Cache": "HIT",
                        }
                    )
                except Exception:
                    logger.debug("Failed to set HIT response headers", exc_info=True)

                if_none_match = _header_get(
                    getattr(request, "headers", None) if request else None, "if-none-match"
                )
                if if_none_match == etag:
                    try:
                        response.status_code = HTTP_304_NOT_MODIFIED
                    except Exception:
                        logger.debug("Failed to set 304 status", exc_info=True)
                    return response

            try:
                if return_type is Any or return_type is inspect.Signature.empty:
                    return cast(R, decode_json(cached))
                return cast(R, decode_json(cached, return_type))
            except Exception:
                logger.warning(
                    "Error decoding cached value for key '%s'; falling back to call",
                    cache_key,
                    exc_info=True,
                )
                return await _call(*args, **kwargs)

        cast(Any, inner).__signature__ = _augment_signature(wrapped_signature, *to_inject)
        return inner

    return wrapper
