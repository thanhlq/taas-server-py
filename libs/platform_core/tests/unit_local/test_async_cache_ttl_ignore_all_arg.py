"""
Tests for `platform_core.utils.cache.async_cache_ttl_ignore_all_arg`.

The decorator supports two usage styles, which are exercised side by side here:

    @async_cache_ttl_ignore_all_arg          # bare
    async def fetch(): ...

    @async_cache_ttl_ignore_all_arg()        # called (with or without kwargs)
    async def fetch(): ...

Command: uv run --package platform_core pytest -v libs/platform_core/tests/unit_local/test_async_cache_ttl_ignore_all_arg.py
"""

from __future__ import annotations

import asyncio

import pytest
from platform_core.utils.cache import async_cache_ttl_ignore_all_arg

pytestmark = pytest.mark.asyncio


# Both decorator styles applied as `decorate(fn)` must behave identically. Each
# style is applied fresh per test, so every test gets its own cache entry.
#   - "bare":   @async_cache_ttl_ignore_all_arg
#   - "called": @async_cache_ttl_ignore_all_arg()
DECORATOR_STYLES = [
    pytest.param(lambda: async_cache_ttl_ignore_all_arg, id="bare"),
    pytest.param(lambda: async_cache_ttl_ignore_all_arg(), id="called"),
]


@pytest.mark.parametrize("make_decorator", DECORATOR_STYLES)
class TestAsyncCacheTtlIgnoreAllArg:
    async def test_caches_result_across_many_calls(self, make_decorator) -> None:
        """Both styles: after the first call the result is reused for every
        subsequent call. Invoked well past the 2-hit window you saw manually."""
        decorate = make_decorator()
        calls = 0

        @decorate
        async def fetch() -> int:
            nonlocal calls
            calls += 1
            return calls

        # At least 3 invocations — only the first one hits the function.
        assert await fetch() == 1
        assert await fetch() == 1
        assert await fetch() == 1
        assert await fetch() == 1
        assert await fetch() == 1
        assert calls == 1

    async def test_ignores_all_arguments(self, make_decorator) -> None:
        """Different positional/keyword args still hit the single shared entry."""
        decorate = make_decorator()
        calls = 0

        @decorate
        async def fetch(a: int, b: int = 0) -> int:
            nonlocal calls
            calls += 1
            return a + b

        first = await fetch(1, b=2)
        # Completely different arguments — the cached value is returned anyway.
        assert await fetch(99, b=100) == first
        assert await fetch(5) == first
        assert await fetch(7, b=8) == first
        assert calls == 1

    async def test_caches_result_not_coroutine(self, make_decorator) -> None:
        """The awaited result is cached, so repeated awaits never re-raise
        'cannot reuse already awaited coroutine'."""
        decorate = make_decorator()

        @decorate
        async def fetch() -> dict[str, int]:
            return {"value": 42}

        first = await fetch()
        second = await fetch()
        third = await fetch()
        assert first == {"value": 42}
        # Same object is handed back; the coroutine is not re-awaited.
        assert first is second
        assert first is third

    async def test_works_as_method_ignoring_self(self, make_decorator) -> None:
        """Used on a method, `self` is ignored like any other argument."""
        decorate = make_decorator()

        class Client:
            def __init__(self) -> None:
                self.calls = 0

            @decorate
            async def fetch_all(self) -> int:
                self.calls += 1
                return self.calls

        a = Client()
        b = Client()
        assert await a.fetch_all() == 1
        # Cache is shared at the function level, so a *different* instance still
        # sees the first cached result.
        assert await b.fetch_all() == 1
        assert await a.fetch_all() == 1
        assert a.calls == 1
        assert b.calls == 0

    async def test_preserves_function_metadata(self, make_decorator) -> None:
        """functools.wraps keeps the original name and docstring."""
        decorate = make_decorator()

        @decorate
        async def fetch() -> None:
            """Original docstring."""

        assert fetch.__name__ == "fetch"
        assert fetch.__doc__ == "Original docstring."

    async def test_concurrent_callers_may_each_invoke_then_warm(self, make_decorator) -> None:
        """There is no in-flight de-duplication: concurrent awaits before the
        cache is populated each invoke the coroutine (this is the "hits the
        function twice and then works fine" behaviour). Once warm, no more hits."""
        decorate = make_decorator()
        calls = 0

        @decorate
        async def fetch() -> int:
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.01)
            return calls

        # Concurrent cold callers may each execute the body...
        results = await asyncio.gather(fetch(), fetch(), fetch())
        assert all(r >= 1 for r in results)
        assert calls >= 1

        # ...but once warm, 3+ subsequent calls never invoke the coroutine again.
        warm_calls = calls
        await fetch()
        await fetch()
        await fetch()
        assert calls == warm_calls

    async def test_entry_expires_after_ttl(self, make_decorator) -> None:
        """Once the TTL elapses the coroutine is invoked again. Uses ttl=1 for
        the parameterized style; the bare style falls back to the configured
        default TTL (so it stays cached for the whole test)."""
        # This behaviour is TTL-specific, so drive it through an explicit ttl.
        calls = 0

        @async_cache_ttl_ignore_all_arg(ttl=1)
        async def fetch() -> int:
            nonlocal calls
            calls += 1
            return calls

        assert await fetch() == 1
        assert await fetch() == 1
        assert await fetch() == 1
        assert calls == 1

        # Wait just past the 1-second TTL window.
        await asyncio.sleep(1.1)

        assert await fetch() == 2
        assert await fetch() == 2
        assert calls == 2
