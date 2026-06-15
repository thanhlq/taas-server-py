"""Shared test fixtures for ``banking_core``.

This module hosts everything that is independent of *where* the database lives:

* environment bootstrapping (loads ``.env.test`` before any app import),
* the crypto-token factory used to build test data (BTC, ETH, SOL, KAS, ...),
* the schema / session / cleanup machinery that operates on whatever engine the
  layer-specific conftest provides.

The only thing that differs between the two test layers is *how* the database
connection is obtained, expressed through a single ``db_url`` fixture:

* ``tests/unit/conftest.py``      -> spins up a throw-away Postgres testcontainer
* ``tests/unit_dev/conftest.py``  -> points at the developer's local database

Everything downstream of ``db_url`` (engine, schema, session, services,
factories) is defined here once and reused by both layers.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Generator
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

import pytest
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Environment bootstrap
#
# Settings modules read ``os.environ`` (and cache it) on first import, so the
# test environment has to be in place *before* any ``banking_core`` / ``db``
# import happens. Importing this conftest is the earliest hook pytest gives us.
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    """Walk upwards until the workspace root (the dir holding ``.env.test``)."""
    for parent in Path(__file__).resolve().parents:
        if (parent / ".env.test").exists():
            return parent
    # Fall back to the server root if the marker file is missing.
    return Path(__file__).resolve().parents[3]


load_dotenv(_repo_root() / ".env.test", override=True)

# App imports must come *after* the environment has been configured.
import db.models.banking as banking_models  # noqa: E402
from banking_core.crypto.schemas import CryptoToken as CryptoTokenCreate  # noqa: E402
from banking_core.crypto.services._crypto_token import CryptoTokenService  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool  # noqa: E402

if TYPE_CHECKING:
    from sqlalchemy import Table
    from sqlalchemy.ext.asyncio import AsyncEngine

_T = TypeVar("_T")

# Tables owned by ``banking_core``. We create / truncate only these so the suite
# stays self-contained and never touches unrelated application data (important
# for the ``unit_dev`` layer, which runs against a shared local database).
BANKING_TABLES: list[Table] = [
    getattr(banking_models, name).__table__ for name in banking_models.__all__
]


def _run_sync(coro: Awaitable[_T]) -> _T:
    """Run an awaitable on a throw-away event loop.

    Used by *sync* session-scoped fixtures (engine/schema) so they never bind
    the engine to a specific test's loop — per-test sessions get a fresh
    connection via ``NullPool`` instead.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Engine / schema (session scoped)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def db_engine(db_url: str) -> Generator[AsyncEngine, None, None]:
    """Async engine bound to the URL supplied by the active test layer.

    ``NullPool`` is used so connections are never shared across event loops —
    this keeps a session-scoped engine compatible with function-scoped async
    tests. The banking schema is created on setup and dropped on teardown.
    """
    engine = create_async_engine(db_url, echo=False, poolclass=NullPool)

    async def _create_schema() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(
                banking_models.CryptoToken.metadata.create_all,
                tables=BANKING_TABLES,
                checkfirst=True,
            )

    _run_sync(_create_schema())

    yield engine

    async def _dispose() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(
                banking_models.CryptoToken.metadata.drop_all,
                tables=BANKING_TABLES,
                checkfirst=True,
            )
        await engine.dispose()

    _run_sync(_dispose())


@pytest.fixture(scope="session")
def sessionmaker(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Session factory bound to the test engine."""
    return async_sessionmaker(bind=db_engine, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Per-test session (function scoped, isolated)
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_session(
    db_engine: AsyncEngine,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """A fresh ``AsyncSession`` per test, with banking tables emptied afterwards.

    Truncating only the banking tables keeps each test isolated while leaving
    any surrounding data (relevant for the local-database layer) untouched.
    """
    async with sessionmaker() as session:
        yield session

    table_names = ", ".join(f'"{t.name}"' for t in BANKING_TABLES)
    async with db_engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE"))


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------


@pytest.fixture
def crypto_token_service(db_session: AsyncSession) -> CryptoTokenService:
    """``CryptoTokenService`` bound to the per-test session."""
    return CryptoTokenService(session=db_session)


# ---------------------------------------------------------------------------
# Test-data factory
# ---------------------------------------------------------------------------


class CryptoTokenFactory:
    """Builds :class:`CryptoTokenCreate` payloads for tests.

    Provides ready-made presets for common tokens (BTC, ETH, SOL, KAS) plus a
    generic :meth:`build` for ad-hoc tokens. Every preset can be tweaked with
    keyword overrides, e.g. ``CryptoTokenFactory.eth(network="sepolia")``.
    """

    # symbol -> default field values
    PRESETS: dict[str, dict[str, Any]] = {
        "BTC": {
            "name": "Bitcoin",
            "blockchain": "bitcoin",
            "decimals": 8,
            "chain_id": None,
        },
        "ETH": {
            "name": "Ethereum",
            "blockchain": "ethereum",
            "decimals": 18,
            "chain_id": 1,
        },
        "SOL": {
            "name": "Solana",
            "blockchain": "solana",
            "decimals": 9,
            "chain_id": None,
        },
        "KAS": {
            "name": "Kaspa",
            "blockchain": "kaspa",
            "decimals": 8,
            "chain_id": None,
        },
    }

    @classmethod
    def build(cls, symbol: str, **overrides: Any) -> CryptoTokenCreate:
        """Build a token payload for ``symbol`` (preset if known, else generic)."""
        symbol = symbol.upper()
        preset = cls.PRESETS.get(symbol, {})
        fields: dict[str, Any] = {
            "name": preset.get("name", symbol.title()),
            "symbol": symbol,
            "short_name": symbol,
            "blockchain": preset.get("blockchain", symbol.lower()),
            "network": "mainnet",
            "type": "NATIVE",
            "decimals": preset.get("decimals", 18),
            "chain_id": preset.get("chain_id"),
            "enabled": True,
        }
        fields.update(overrides)
        return CryptoTokenCreate(**fields)

    @classmethod
    def btc(cls, **overrides: Any) -> CryptoTokenCreate:
        return cls.build("BTC", **overrides)

    @classmethod
    def eth(cls, **overrides: Any) -> CryptoTokenCreate:
        return cls.build("ETH", **overrides)

    @classmethod
    def sol(cls, **overrides: Any) -> CryptoTokenCreate:
        return cls.build("SOL", **overrides)

    @classmethod
    def kas(cls, **overrides: Any) -> CryptoTokenCreate:
        return cls.build("KAS", **overrides)

    @classmethod
    def all_presets(cls) -> list[CryptoTokenCreate]:
        """One payload per known preset — handy for seeding the database."""
        return [cls.build(symbol) for symbol in cls.PRESETS]


@pytest.fixture
def token_factory() -> type[CryptoTokenFactory]:
    """Expose the crypto-token factory to tests."""
    return CryptoTokenFactory
