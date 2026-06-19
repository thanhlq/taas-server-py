# Original: https://github.com/kaspanet/kaspa-python-sdk/blob/main/examples/transactions/estimate.py

import datetime
import json
import asyncio
from kaspa import Generator, Resolver, RpcClient, kaspa_to_sompi, UtxoEntries

NETWORK_ID = 'mainnet'  # or "testnet-10"
AMOUNT: float = 0.5  # 0.2 KASPA
PRIORITY_FEE: float = 0.0002  # 0.0002


async def main():

    source_address = (
        'kaspa:qp2z9h8ggqshjwqucpd0hlrzepuq8v6pvq7fmgqavj9ksztxx2ulktvfeyhrr'
    )
    print(f'Source Address: {source_address}')

    client = RpcClient(resolver=Resolver(), network_id=NETWORK_ID)  # type: ignore

    print(f'Connecting to Kaspa {NETWORK_ID} RPC...')
    await client.connect()
    print(f'Connected to Kaspa RPC: {client.url}')

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
        outputs=[{'address': source_address, 'amount': kaspa_to_sompi(AMOUNT)}],
        priority_fee=kaspa_to_sompi(PRIORITY_FEE),
        change_address=source_address,
    )

    estimate = generator.estimate()
    print(
        f'Estimated fee: {estimate.final_transaction_id} for sending {AMOUNT} KASPA with priority fee {PRIORITY_FEE} KASPA'
    )

    await client.disconnect()


if __name__ == '__main__':
    asyncio.run(main())
