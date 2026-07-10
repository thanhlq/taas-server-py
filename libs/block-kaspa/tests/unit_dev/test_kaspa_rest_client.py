"""
The purpose is to test this file: taas-server-py/libs/block-kaspa/src/block_kaspa/client_rest/kaspa_rest_client.py

The env should be loaded from taas-server-py/.env

if the KASPA_NETWORK is mainnet, the fixtures is in taas-server-py/libs/block-kaspa/tests/fixtures/mainnet
if the KASPA_NETWORK is testnet, the fixtures is in taas-server-py/libs/block-kaspa/tests/fixtures/testnet

Data:
- transaction ids in each file name in tests/fixtures/testnet/transactions
- to test get utxos by address, the utxos data is in tests/fixtures/testnet/utxos

Tests are deterministic: the fixtures (captured real responses) are served back via
`respx` (httpx mock), so they exercise the client's parsing + status handling without
hitting the live network. The conftest loads `.env` and selects the fixture directory.

Execute test: uv run pytest libs/block-kaspa/tests/unit_dev/test_kaspa_rest_client.py -v

"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest
import respx

from block_kaspa.client_rest.kaspa_rest_client import KaspaRestClient
from block_kaspa.types import TxModel, UtxoModel
from foundation.exceptions import NotFoundException

# Resolved at collection time (conftest has already loaded .env on import).
_NETWORK = "mainnet" if "main" in (os.environ.get("KASPA_NETWORK") or "testnet").lower() else "testnet"
_TX_DIR = Path(__file__).resolve().parents[1] / "fixtures" / _NETWORK / "transactions"
# Transaction ids are the fixture file names (without extension).
_TX_IDS = sorted(p.stem for p in _TX_DIR.glob("*.json")) if _TX_DIR.exists() else []


class TestKaspaRestClient:
    async def test_get_utxos_parses_fixture(
        self, rest_client: KaspaRestClient, fixtures_dir: Path
    ) -> None:
        raw = (fixtures_dir / "utxos" / "utxos.json").read_bytes()
        expected = json.loads(raw)
        address = expected[0]["address"]

        with respx.mock:
            route = respx.get(f"{rest_client._url}/addresses/{address}/utxos").mock(
                return_value=httpx.Response(200, content=raw)
            )
            result = await rest_client.get_utxos(address)

        assert route.called
        assert isinstance(result, list)
        assert len(result) == len(expected)
        assert all(isinstance(u, UtxoModel) for u in result)

        # The client returns each UtxoResponse.utxoEntry (a UtxoModel).
        first, exp_entry = result[0], expected[0]["utxoEntry"]
        assert first.amount == exp_entry["amount"]
        assert first.scriptPublicKey.scriptPublicKey == exp_entry["scriptPublicKey"]["scriptPublicKey"]
        assert first.isCoinbase == exp_entry["isCoinbase"]

    async def test_get_utxos_404_raises_not_found(self, rest_client: KaspaRestClient) -> None:
        address = "kaspa:doesnotexist"
        with respx.mock:
            respx.get(f"{rest_client._url}/addresses/{address}/utxos").mock(
                return_value=httpx.Response(404)
            )
            with pytest.raises(NotFoundException):
                await rest_client.get_utxos(address)

    @pytest.mark.skipif(not _TX_IDS, reason=f"no transaction fixtures for network {_NETWORK!r}")
    @pytest.mark.parametrize("tx_id", _TX_IDS)
    async def test_get_transaction_by_id_parses_fixture(
        self, rest_client: KaspaRestClient, fixtures_dir: Path, tx_id: str
    ) -> None:
        raw = (fixtures_dir / "transactions" / f"{tx_id}.json").read_bytes()
        expected = json.loads(raw)

        with respx.mock:
            # The client also sends query params; respx matches the path regardless.
            route = respx.get(f"{rest_client._url}/transactions/{tx_id}").mock(
                return_value=httpx.Response(200, content=raw)
            )
            tx = await rest_client.get_transaction_by_id(tx_id)

        assert route.called
        assert isinstance(tx, TxModel)
        assert tx.transaction_id == tx_id
        assert tx.hash == expected.get("hash")
        # get_transaction_by_id raises if this is missing, so it must be present.
        assert tx.accepting_block_blue_score is not None

    async def test_get_transaction_404_raises_not_found(self, rest_client: KaspaRestClient) -> None:
        tx_id = "deadbeef"
        with respx.mock:
            respx.get(f"{rest_client._url}/transactions/{tx_id}").mock(
                return_value=httpx.Response(404)
            )
            with pytest.raises(NotFoundException):
                await rest_client.get_transaction_by_id(tx_id)
