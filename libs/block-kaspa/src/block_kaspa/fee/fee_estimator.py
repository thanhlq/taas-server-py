"""
Kaspa fee estimator by using official Kaspa Wasm SDK: https://github.com/kaspanet/kaspa-python-sdk

See sample: https://github.com/kaspanet/kaspa-python-sdk/blob/main/examples/transactions/estimate.py
"""
from block_kaspa.types import FeeEstimate
from block_kaspa.config import KaspaSettings

import asyncio
from ..kaspa_client import KaspaRpcClient
from kaspa import Generator, PrivateKey, Resolver, RpcClient, kaspa_to_sompi

async def estimate_fee(
    source_address: str,
    send_amount: int,

    utxo_amounts: list[int],
    send_amount: int,
    *,
    feerate: float = MINIMUM_FEERATE,
    priority_fee: int = 0,
    output_script_len: int = 34,  # P2PK script: 0x20 + 32-byte key + 0xac
    payload_len: int = 0,
    select_utxos: bool = True,
) -> FeeEstimate:

    pass
