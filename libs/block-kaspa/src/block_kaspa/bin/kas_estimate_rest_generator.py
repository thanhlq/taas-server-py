# uv run python -m block_kaspa.bin.kas_estimate_rest_generator
from foundation.bootstrap import load_environment

load_environment()

import asyncio


from block_kaspa.transaction.fee_estimator import KaspaFeeEstimator

#######################
# mainnet
#######################
NETWORK_ID = 'mainnet'  # or "testnet-10"
AMOUNT: float = 0.5  # 0.2 KASPA
# PRIORITY_FEE: float = 0.0002  # 0.0002
PRIORITY_FEE: float = 0.0002  # 0.0002
# Fee: 223600
SOURCE_ADDRESS = 'kaspa:qp2z9h8ggqshjwqucpd0hlrzepuq8v6pvq7fmgqavj9ksztxx2ulktvfeyhrr'

# Has > 12k UTXOs
# SOURCE_ADDRESS = 'kaspa:qqywx2wszmnrsu0mzgav85rdwvzangfpdj9j3ady9jpr7hu4u8c2wl9wqgd6j'

# Has ~1k UTXOs
# Fee: 337600
# SOURCE_ADDRESS = 'kaspa:precqv0krj3r6uyyfa36ga7s0u9jct0v4wg8ctsfde2gkrsgwgw8jgxfzfc98'

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
