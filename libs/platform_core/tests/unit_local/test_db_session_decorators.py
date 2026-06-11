from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest
from http_fastapi.adapters._controller import _retarget_cache_injected_params
from http_litestar.adapters._dependencies import adapt_handler
from platform_core.db import advanced_session_manager as asm
from sqlalchemy.ext.asyncio import AsyncSession


class DummySession:
    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def close(self) -> None:
        return None


class DummySessionGenerator:
    def __init__(self, session: DummySession) -> None:
        self._session = session

    async def __aenter__(self) -> DummySession:
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class DummyMainDatabase:
    def __init__(self, session: DummySession) -> None:
        self._session = session

    def get_current_context_session(self) -> DummySession | None:
        return None

    def get_session_generator(self, transaction: bool = False):
        return DummySessionGenerator(self._session)


class DummyConcurrentRegistry:
    def __init__(self) -> None:
        self.registry = SimpleNamespace(values=lambda: [])


class DummyConcurrentScopedFactory:
    def __init__(self, session: object) -> None:
        self._session = session
        self.registry = DummyConcurrentRegistry()

    def __call__(self) -> object:
        return self._session


class DummyConcurrentFactory:
    def __init__(self) -> None:
        self.session = object()
        self.scoped_session_factory = DummyConcurrentScopedFactory(self.session)

    def get_session(self) -> object:
        return self.session

    @staticmethod
    async def commit_sessions(sessions) -> None:
        return None

    @staticmethod
    async def rollback_sessions(sessions) -> None:
        return None

    @staticmethod
    async def close_sessions(sessions) -> None:
        return None


@pytest.mark.asyncio
async def test_db_context_session_injects_actual_parameter_name(monkeypatch) -> None:
    session = DummySession()
    monkeypatch.setattr(
        asm.MainDatabase,
        "get_instance",
        classmethod(lambda cls: DummyMainDatabase(session)),
    )

    @asm.db_context_session
    async def work(*, sesson: AsyncSession) -> DummySession:
        return sesson

    assert await work() is session


@pytest.mark.asyncio
async def test_db_concurrent_session_injects_actual_parameter_name(monkeypatch) -> None:
    monkeypatch.setattr(asm, "DBConcurrentSessionFactory", DummyConcurrentFactory)

    @asm.db_concurrent_session
    async def work(*, manager: asm.DBConcurrentSessionFactory) -> object:
        return manager

    result = await work()
    assert isinstance(result, DummyConcurrentFactory)


def test_fastapi_adapter_strips_db_managed_parameter() -> None:
    async def handler(self, session: AsyncSession | None = None) -> None:
        return None

    wrapped = _retarget_cache_injected_params(handler)
    signature = inspect.signature(wrapped)
    assert "session" not in signature.parameters


def test_litestar_adapter_strips_db_managed_parameter() -> None:
    async def handler(self, session: AsyncSession | None = None) -> None:
        return None

    adapted, dependencies = adapt_handler(handler)
    signature = inspect.signature(adapted)
    assert "session" not in signature.parameters
    assert dependencies == {}
