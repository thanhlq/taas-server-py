# Original: https://github.com/kaspanet/kaspa-python-sdk/blob/main/examples/transactions/estimate.py
# uv run python libs/block-kaspa/src/block_kaspa/bin/kas_estimate.py
# uv run python -m block_kaspa.bin.kas_estimate_rpc

import datetime
import json
import asyncio
from kaspa import (
    Address,
    Generator,
    PaymentOutput,
    kaspa_to_sompi,
    UtxoEntries,
)

from foundation.bootstrap import load_environment
load_environment()

from ..client_rpc.kaspa_rpc_client import KaspaRpcClient

#######################
# mainnet
#######################
NETWORK_ID = 'mainnet'  # or "testnet-10"
AMOUNT: float = 0.5  # 0.2 KASPA
PRIORITY_FEE: float = 0.0002  # 0.0002
SOURCE_ADDRESS = 'kaspa:qp2z9h8ggqshjwqucpd0hlrzepuq8v6pvq7fmgqavj9ksztxx2ulktvfeyhrr'


async def main():

    source_address = SOURCE_ADDRESS
    print(f'Source Address: {source_address}')

    # client = RpcClient(resolver=Resolver(), network_id=NETWORK_ID)  # type: ignore
    #
    # client = RpcClient(url='wss://kas.nownodes.io/?api-key=059f0223-f5b1-4855-8dcc-4e4b69a00210', network_id=NETWORK_ID)  # type: ignore

    print(f'Connecting to Kaspa {NETWORK_ID} RPC...')
    # await client.connect()
    # print(f'Connected to Kaspa RPC: {client.url}')

    client = await KaspaRpcClient().connect()


    entries = await client.get_utxos_by_addresses({'addresses': [source_address]})

    if not entries['entries'] or len(entries['entries']) == 0:
        print(f'No UTXOs found for address {source_address}')
        return
    else:
        print(f'Found {len(entries["entries"])} UTXOs for address {source_address}')
        print(entries)

    with open(
        f'{source_address}-utxos-{datetime.datetime.now().isoformat()}.json', 'w'
    ) as file:
        json.dump(entries, file)

    entries: UtxoEntries = entries['entries']
    print(entries)

    generator = Generator(
        network_id=NETWORK_ID,
        entries=entries,
        # NOTE: pass typed PaymentOutput objects, not plain dicts. In kaspa
        # 2.0.0 the dict form is parsed via TransactionOutput.from_dict, which
        # requires a 'covenant' key even though it is documented as optional,
        # and raises `KeyError: 'covenant'` when omitted.
        outputs=[PaymentOutput(Address(source_address), kaspa_to_sompi(AMOUNT))],  # type: ignore
        priority_fee=kaspa_to_sompi(PRIORITY_FEE),
        change_address=source_address,
    )

    estimate = generator.estimate()
    print(
        f'Estimated fee: {estimate.fees} for sending {AMOUNT} KASPA with priority fee {PRIORITY_FEE} KASPA'
    )
    print(estimate)

    await client.disconnect()


if __name__ == '__main__':
    asyncio.run(main())
