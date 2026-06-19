"""
Kaspa fee estimator by using official Kaspa Wasm SDK: https://github.com/kaspanet/kaspa-python-sdk
"""
from block_kaspa.types import FeeEstimate
from block_kaspa.config import KaspaSettings

import asyncio
from ..kaspa_client import KaspaRpcClient
from kaspa import Generator, PrivateKey, Resolver, RpcClient, kaspa_to_sompi

def estimate_fee(
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

async def main():
    private_key = PrivateKey(
        "e7e44bc3682be46c771b3949243a7c564449773f6c459031ff5e9dfc7759c361")

    source_address = private_key.to_keypair().to_address("testnet")
    print(f'Source Address: {source_address.to_string()}')

    kaspa_client = KaspaRpcClient(settings=KaspaSettings())
    client = await kaspa_client.connect()

    entries = await client.get_utxos_by_addresses({"addresses": [source_address]})

    generator = Generator(
        network_id="testnet-10",
        entries=entries["entries"],
        outputs=[{"address": source_address, "amount": kaspa_to_sompi(0.2)}],
        priority_fee=kaspa_to_sompi(0.0002),
        change_address=source_address
    )

    estimate = generator.estimate()
    print(estimate.final_transaction_id)

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
