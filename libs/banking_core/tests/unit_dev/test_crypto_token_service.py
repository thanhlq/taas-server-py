"""CryptoTokenService tests — ``unit_dev`` layer (runs against the local database).

Identical coverage to the ``unit`` layer, but backed by the developer's local
PostgreSQL instance (configured via ``.env.test``) for a fast inner-loop with
no Docker dependency. Exercises the CRUD surface of
:class:`banking_core.crypto.services._crypto_token.CryptoTokenService` using the
crypto-token factory (BTC, ETH, SOL, KAS).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from banking_core.crypto.services._crypto_token import CryptoTokenService

if TYPE_CHECKING:
    # Resolved by type-checkers via `pythonpath` in pyproject; never imported at
    # runtime (annotations are strings), so the factory is used via fixtures.
    from tests.conftest import CryptoTokenFactory


async def test_create_crypto_token(
    crypto_token_service: CryptoTokenService,
    token_factory: type[CryptoTokenFactory],
) -> None:
    created = await crypto_token_service.create_crypto_token(token_factory.btc())

    assert created.id is not None
    assert created.symbol == "BTC"
    assert created.name == "Bitcoin"
    assert created.blockchain == "bitcoin"
    assert created.decimals == 8


async def test_get_crypto_token_by_id(
    crypto_token_service: CryptoTokenService,
    token_factory: type[CryptoTokenFactory],
) -> None:
    created = await crypto_token_service.create_crypto_token(token_factory.eth())

    fetched = await crypto_token_service.get(created.id)

    assert fetched.id == created.id
    assert fetched.symbol == "ETH"
    assert fetched.chain_id == 1


async def test_create_all_preset_tokens(
    crypto_token_service: CryptoTokenService,
    token_factory: type[CryptoTokenFactory],
) -> None:
    for payload in token_factory.all_presets():
        await crypto_token_service.create_crypto_token(payload)

    tokens = await crypto_token_service.get_many()
    symbols = {token.symbol for token in tokens}

    assert symbols == {"BTC", "ETH", "SOL", "KAS"}
    assert await crypto_token_service.count() == 4


async def test_factory_overrides(
    crypto_token_service: CryptoTokenService,
    token_factory: type[CryptoTokenFactory],
) -> None:
    created = await crypto_token_service.create_crypto_token(
        token_factory.eth(network="sepolia", chain_id=11155111)
    )

    assert created.network == "sepolia"
    assert created.chain_id == 11155111
    # Untouched preset fields remain intact.
    assert created.symbol == "ETH"
    assert created.decimals == 18


async def test_delete_crypto_token(
    crypto_token_service: CryptoTokenService,
    token_factory: type[CryptoTokenFactory],
) -> None:
    created = await crypto_token_service.create_crypto_token(token_factory.sol())

    await crypto_token_service.delete(created.id)

    assert await crypto_token_service.get_one_or_none(id=created.id) is None
    assert await crypto_token_service.count() == 0


async def test_isolation_between_tests(
    crypto_token_service: CryptoTokenService,
    token_factory: type[CryptoTokenFactory],
) -> None:
    # Proves the per-test truncation worked: the table starts empty even though
    # previous tests created rows.
    assert await crypto_token_service.count() == 0

    await crypto_token_service.create_crypto_token(token_factory.kas())
    assert await crypto_token_service.count() == 1


@pytest.mark.parametrize("symbol", ["BTC", "ETH", "SOL", "KAS"])
async def test_create_each_token_symbol(
    crypto_token_service: CryptoTokenService,
    token_factory: type[CryptoTokenFactory],
    symbol: str,
) -> None:
    created = await crypto_token_service.create_crypto_token(token_factory.build(symbol))

    assert created.symbol == symbol
    assert created.short_name == symbol
