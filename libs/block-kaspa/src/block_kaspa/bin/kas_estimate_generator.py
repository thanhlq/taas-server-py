# uv run python -m block_kaspa.bin.kas_estimate_generator
from platform_core.bootstrap import load_environment

load_environment()

import datetime
import json
import asyncio
from kaspa import (
    Address,
    Generator,
    PaymentOutput,
    Resolver,
    RpcClient,
    kaspa_to_sompi,
    UtxoEntries,
)


from block_kaspa.transaction.fee_estimator import KaspaFeeEstimator

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

    await KaspaFeeEstimator().estimate_fee(
        source_address=source_address,
        send_amount=AMOUNT,
        network_id=NETWORK_ID,
        priority_fee=PRIORITY_FEE,
    )


if __name__ == '__main__':
    asyncio.run(main())
