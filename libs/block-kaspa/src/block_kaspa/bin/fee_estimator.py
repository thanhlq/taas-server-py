"""
Kaspa fee estimator by using official Kaspa Wasm SDK: https://github.com/kaspanet/kaspa-python-sdk
"""
from platform_core.bootstrap import load_environment
load_environment()


from block_kaspa.config import KaspaSettings

import asyncio
from ..client_rest import KaspaRestClient
from kaspa import Generator, PrivateKey, Resolver, RpcClient, kaspa_to_sompi


async def estimate_fee(
    source_address: str,
    send_amount: int,
    *,
    feerate: float = MINIMUM_FEERATE,
    priority_fee: int = 0,
    output_script_len: int = 34,  # P2PK script: 0x20 + 32-byte key + 0xac
    payload_len: int = 0,
) -> FeeEstimate:
    kaspa_client = KaspaRestClient()
    client = await kaspa_client.connect()

    entries = await client.get_utxos_by_addresses({"addresses": [source_address]})

    generator = Generator(
        network_id="testnet-10",
        entries=entries["entries"],
        outputs=[{"address": source_address, "amount": kaspa_to_sompi(send_amount)}],
        priority_fee=kaspa_to_sompi(priority_fee),
        change_address=source_address
    )

    estimate = generator.estimate()
    print(estimate.final_transaction_id)

    await client.disconnect()


async def main():


if __name__ == "__main__":
    asyncio.run(main())
