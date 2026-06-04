"""
Tests for `platform_core.utils.cache.async_cache_ttl_ignore_first_arg`.

The decorator caches a coroutine's awaited result keyed on every argument
*except the first* (typically ``self``). It supports two usage styles, both
exercised here:

    @async_cache_ttl_ignore_first_arg          # bare
    async def fetch(self, key): ...

    @async_cache_ttl_ignore_first_arg()        # called (with or without kwargs)
    async def fetch(self, key): ...

Command: uv run --package platform_core pytest -v libs/platform_core/tests/unit_local/test_async_cache_ttl_ignore_first_arg.py
"""

from __future__ import annotations

import pytest
from platform_core.utils.cache import a_ttl_cache_ignore_1st_arg

pytestmark = pytest.mark.asyncio


# Both decorator styles applied as `decorate(fn)` must behave identically.
#   - "bare":   @async_cache_ttl_ignore_first_arg
#   - "called": @async_cache_ttl_ignore_first_arg()
DECORATOR_STYLES = [
    pytest.param(lambda: a_ttl_cache_ignore_1st_arg, id="bare"),
    pytest.param(lambda: a_ttl_cache_ignore_1st_arg(), id="called"),
]


@pytest.mark.parametrize("make_decorator", DECORATOR_STYLES)
class TestAsyncCacheTtlIgnoreFirstArg:
    async def test_caches_result_across_many_calls(self, make_decorator) -> None:
        """Both styles: same trailing args reuse the cached result; only the
        first call hits the function. Invoked 5x to be well past any warm-up."""
        decorate = make_decorator()
        calls = 0

        @decorate
        async def fetch(self_, key: str) -> int:
            nonlocal calls
            calls += 1
            return calls

        assert await fetch("self-a", "k") == 1
        assert await fetch("self-a", "k") == 1
        assert await fetch("self-a", "k") == 1
        assert await fetch("self-a", "k") == 1
        assert await fetch("self-a", "k") == 1
        assert calls == 1

    async def test_first_arg_is_ignored(self, make_decorator) -> None:
        """A different first arg (self) still hits the same cache entry."""
        decorate = make_decorator()
        calls = 0

        @decorate
        async def fetch(self_, key: str) -> int:
            nonlocal calls
            calls += 1
            return calls

        first = await fetch("self-a", "k")
        # Different first arg, same remaining args -> cached value reused.
        assert await fetch("self-b", "k") == first
        assert await fetch("self-c", "k") == first
        assert calls == 1

    async def test_distinct_remaining_args_are_separate_entries(self, make_decorator) -> None:
        """Args beyond the first DO participate in the key."""
        decorate = make_decorator()
        calls = 0

        @decorate
        async def fetch(self_, key: str) -> str:
            nonlocal calls
            calls += 1
            return f"{key}-{calls}"

        a1 = await fetch("self", "alpha")
        b1 = await fetch("self", "beta")
        assert a1 != b1
        # Each distinct key keeps its own cached result across repeated calls.
        assert await fetch("self", "alpha") == a1
        assert await fetch("self", "beta") == b1
        assert await fetch("self", "alpha") == a1
        assert calls == 2

    async def test_works_as_method_ignoring_self(self, make_decorator) -> None:
        """On a real method, `self` (the first arg) is ignored, so different
        instances share one cached result for the same remaining args."""
        decorate = make_decorator()
        calls = 0

        class Client:
            @decorate
            async def fetch(self, key: str) -> int:
                nonlocal calls
                calls += 1
                return calls

        a = Client()
        b = Client()
        assert await a.fetch("k") == 1
        assert await b.fetch("k") == 1  # different self, same key -> cached
        assert await a.fetch("k") == 1
        assert calls == 1

    async def test_preserves_function_metadata(self, make_decorator) -> None:
        """functools.wraps keeps the original name and docstring."""
        decorate = make_decorator()

        @decorate
        async def fetch(self_) -> None:
            """Original docstring."""

        assert fetch.__name__ == "fetch"
        assert fetch.__doc__ == "Original docstring."
