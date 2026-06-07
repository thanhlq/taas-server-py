"""Bridge FastAPI-style handler signatures into Litestar primitives.

The framework-agnostic controllers in ``platform_core.http`` are sometimes
authored against FastAPI conventions:

* dependency injection via :func:`fastapi.Depends` (often hidden inside an
  ``Annotated[...]`` type alias, e.g. ``Annotated[UserService, Depends(...)]``),
* untyped path parameters (``/{user_id}`` rather than Litestar's
  ``/{user_id:uuid}``).

FastAPI understands those natively; Litestar does not. This module translates a
handler (and, recursively, its dependency providers) into the shape Litestar
expects:

* ``Depends`` markers are stripped from the signature and re-expressed as a
  Litestar ``dependencies`` mapping of :class:`litestar.di.Provide`,
* synthetic ``request``/``response`` params injected by
  ``platform_core.http.cache`` are removed,
* path parameters are given an explicit Litestar type based on the handler's
  annotation.

The translation is duck-typed against FastAPI's ``Depends`` (matched by class
name + ``dependency`` attribute) so this package does not need a hard FastAPI
dependency.
"""
from __future__ import annotations

import inspect
import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Callable, get_args, get_type_hints
from uuid import UUID

from litestar.di import Provide

# Maps a Python annotation to the Litestar path-parameter type token.
_PATH_PARAM_TYPES: dict[Any, str] = {
    int: "int",
    float: "float",
    str: "str",
    bool: "bool",
    UUID: "uuid",
    Decimal: "decimal",
    date: "date",
    datetime: "datetime",
    time: "time",
    timedelta: "timedelta",
}

_PATH_PARAM_RE = re.compile(r"\{([^}]+)\}")


def _is_fastapi_depends(obj: Any) -> bool:
    """Duck-typed check for a ``fastapi.params.Depends`` marker."""
    return (
        obj is not inspect.Parameter.empty
        and type(obj).__name__ == "Depends"
        and hasattr(obj, "dependency")
    )


def _split_annotated(hint: Any) -> tuple[Any, tuple[Any, ...]]:
    """Return ``(base_type, metadata)`` for an ``Annotated`` hint.

    Non-annotated hints return ``(hint, ())``.
    """
    if hasattr(hint, "__metadata__"):
        args = get_args(hint)
        return args[0], tuple(args[1:])
    return hint, ()


def _resolve_hints(func: Callable[..., Any]) -> dict[str, Any]:
    """Best-effort ``get_type_hints`` with metadata, falling back to raw."""
    try:
        return get_type_hints(func, include_extras=True)
    except Exception:
        return getattr(func, "__annotations__", {}) or {}


def _depends_callable(param: inspect.Parameter, hint: Any) -> Callable[..., Any] | None:
    """Return the dependency callable for ``param`` if it declares one."""
    if _is_fastapi_depends(param.default):
        dep = getattr(param.default, "dependency", None)
        return dep if dep is not None else _split_annotated(hint)[0]

    base, metadata = _split_annotated(hint)
    for meta in metadata:
        if _is_fastapi_depends(meta):
            dep = getattr(meta, "dependency", None)
            return dep if dep is not None else base
    return None


def _make_wrapper(
    func: Callable[..., Any],
    signature: inspect.Signature,
    annotations: dict[str, Any],
) -> Callable[..., Any]:
    """Wrap ``func`` with a clean signature, preserving its call semantics."""
    if inspect.isasyncgenfunction(func):

        async def wrapper(*args: Any, **kwargs: Any) -> Any:  # type: ignore[misc]
            async for value in func(*args, **kwargs):
                yield value
    elif inspect.iscoroutinefunction(func):

        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await func(*args, **kwargs)
    elif inspect.isgeneratorfunction(func):

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            yield from func(*args, **kwargs)
    else:

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)

    # Deliberately no functools.wraps: it sets ``__wrapped__`` and Litestar's
    # signature model would follow through to the original (dirty) signature.
    wrapper.__name__ = getattr(func, "__name__", "adapted")
    wrapper.__doc__ = getattr(func, "__doc__", None)
    # Resolve forward references against the source module, not this one.
    wrapper.__module__ = getattr(func, "__module__", wrapper.__module__)
    wrapper.__signature__ = signature  # type: ignore[attr-defined]
    wrapper.__annotations__ = annotations
    return wrapper


def _clean_provider(func: Callable[..., Any]) -> Callable[..., Any]:
    """Strip ``Depends`` markers from a dependency provider's signature.

    Dependency params are kept (Litestar injects them by name) but their
    annotation is reduced to the underlying type. Providers without ``Depends``
    params are returned unchanged so generator providers keep their semantics.
    """
    signature = inspect.signature(func)
    hints = _resolve_hints(func)
    new_params: list[inspect.Parameter] = []
    new_annotations: dict[str, Any] = {}
    changed = False

    for name, param in signature.parameters.items():
        hint = hints.get(name, param.annotation)
        if _depends_callable(param, hint) is not None:
            changed = True
            base = _split_annotated(hint)[0]
            new_params.append(
                param.replace(annotation=base, default=inspect.Parameter.empty)
            )
            if base is not inspect.Parameter.empty:
                new_annotations[name] = base
        else:
            new_params.append(param)
            if name in hints:
                new_annotations[name] = hints[name]

    if "return" in hints:
        new_annotations["return"] = hints["return"]

    if not changed:
        return func
    return _make_wrapper(func, signature.replace(parameters=new_params), new_annotations)


def _collect_dependencies(
    func: Callable[..., Any], deps: dict[str, Provide]
) -> None:
    """Recursively register ``Depends`` providers reachable from ``func``."""
    signature = inspect.signature(func)
    hints = _resolve_hints(func)
    for name, param in signature.parameters.items():
        provider = _depends_callable(param, hints.get(name, param.annotation))
        if provider is None or name in deps:
            continue
        # Litestar refuses to cache generator dependencies (it manages their
        # teardown per request); cache the rest to mirror FastAPI's per-request
        # dependency caching.
        is_generator = inspect.isasyncgenfunction(provider) or inspect.isgeneratorfunction(
            provider
        )
        deps[name] = Provide(_clean_provider(provider), use_cache=not is_generator)
        _collect_dependencies(provider, deps)


def adapt_handler(
    handler: Callable[..., Any],
) -> tuple[Callable[..., Any], dict[str, Provide]]:
    """Return a Litestar-ready handler plus its dependency mapping.

    * synthetic ``@cache`` request/response params are dropped,
    * ``Depends`` params are kept but their annotation is cleaned and the
      provider is registered as a :class:`Provide`,
    * all other params are passed through untouched.
    """
    injected = set(getattr(handler, "__cache_injected_params__", ()) or ())
    dependencies: dict[str, Provide] = {}
    _collect_dependencies(handler, dependencies)

    if not injected and not dependencies:
        return handler, dependencies

    signature = inspect.signature(handler)
    hints = _resolve_hints(handler)
    new_params: list[inspect.Parameter] = []
    new_annotations: dict[str, Any] = {}

    for name, param in signature.parameters.items():
        if name in injected:
            continue  # drop synthetic cache request/response params
        hint = hints.get(name, param.annotation)
        if _depends_callable(param, hint) is not None:
            base = _split_annotated(hint)[0]
            new_params.append(
                param.replace(annotation=base, default=inspect.Parameter.empty)
            )
            if base is not inspect.Parameter.empty:
                new_annotations[name] = base
        else:
            new_params.append(param)
            if name in hints:
                new_annotations[name] = hints[name]

    if "return" in hints:
        new_annotations["return"] = hints["return"]

    cleaned = _make_wrapper(
        handler, signature.replace(parameters=new_params), new_annotations
    )
    return cleaned, dependencies


def typed_path(path: str, annotations: dict[str, Any]) -> str:
    """Add Litestar type tokens to untyped ``{param}`` path segments.

    The type is inferred from the handler ``annotations``; unknown or missing
    types default to ``str``. Already-typed segments (``{id:int}``) are left
    untouched.
    """
    if "{" not in path:
        return path

    def _replace(match: re.Match[str]) -> str:
        token = match.group(1)
        if ":" in token:  # already typed
            return "{" + token + "}"
        py_type = annotations.get(token)
        litestar_type = _PATH_PARAM_TYPES.get(py_type, "str")
        return "{" + token + ":" + litestar_type + "}"

    return _PATH_PARAM_RE.sub(_replace, path)
