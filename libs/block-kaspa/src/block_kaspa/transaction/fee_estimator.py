"""
Kaspa fee estimator by using official Kaspa Wasm SDK: https://github.com/kaspanet/kaspa-python-sdk

See sample: https://github.com/kaspanet/kaspa-python-sdk/blob/main/examples/transactions/estimate.py
"""

from typing import Any
from foundation import BaseService
from block_kaspa.kaspa_factory import KaspaFactory
from block_kaspa.client_rest import KaspaRestClient
from block_kaspa.types import FeeEstimate, UtxoResponse
from block_kaspa import KaspaSettings
from kaspa import (
    Generator,
    kaspa_to_sompi,
    GeneratorSummary,
)

from foundation.cli import cli


class KaspaFeeEstimator(BaseService):
    def __init__(self):
        super().__init__()
        self._rest_client: KaspaRestClient = KaspaFactory().get_rest_client()
        self._config: KaspaSettings = KaspaSettings()

    async def estimate_fee(
        self,
        *,
        source_address: str,
        send_amount: float,
        network_id: str,
        utxo_entries: list[UtxoResponse] | None = None,
        priority_fee: float = 0.0001,
        output_script_len: int = 34,  # P2PK script: 0x20 + 32-byte key + 0xac
        payload_len: int = 0,
        select_utxos: bool = True,
    ) -> FeeEstimate:

        rest_client: KaspaRestClient = KaspaFactory().get_rest_client()
        config = KaspaSettings()

        # S1: Count utxos for the source address
        count = await rest_client.count_utxos(source_address)
        if count > config.fee_estimator_max_utxos:
            self.logger.warning(
                f'Kaspa address {source_address} has {count} UTXOs, which exceeds the maximum limit of {config.fee_estimator_max_utxos}. Fee estimation may be inaccurate.'
            )
            """ In fact, This is still not really correct, since:
                - We only handle for 1k UTXOs
                - But what about if 2k, 3k, 4k, 5k, 10k, 20k, 50k, 100k UTXOs? We cannot fetch all UTXOs and estimate the fee.
                - So we need to implement a better solution for this case, e.g.:
                    - Use the Kaspa RPC to fetch UTXOs in batches (e.g., 1k at a time) and estimate the fee incrementally.
                    - Or use a different approach to estimate the fee without fetching all UTXOs, e.g., using a statistical model or historical data.
            """
            return FeeEstimate(
                compute_mass=0,
                storage_mass=0,
                network_mass=0,
                minimum_fee=config.fee_estimator_fallback_feerate,
                fee=config.fee_estimator_fallback_feerate,
                change=0,
                n_inputs=0,
                n_outputs=0,
            )



        # S2: OK, UTX0 count <= 1k records -> fetch all UTXOs and estimate fee
        _utxo_entries: list[UtxoResponse] = await rest_client.get_utxos(source_address)

        # S2.1: Convert UTXO entries to the format required by the Kaspa Generator
        refs: list[dict[str, Any]] = []
        for utxo in _utxo_entries:
            ref: dict[str, Any] = {
                'address': utxo.address,
                'outpoint': {
                    'transactionId': utxo.outpoint.transactionId,
                    'index': utxo.outpoint.index,
                },
                'utxoEntry': {
                    'amount': int(utxo.utxoEntry.amount),  # type: ignore
                    'scriptPublicKey': utxo.utxoEntry.scriptPublicKey.scriptPublicKey,
                    'blockDaaScore': int(utxo.utxoEntry.blockDaaScore),  # type: ignore
                    'isCoinbase': utxo.utxoEntry.isCoinbase,
                    'covenantId': None,
                },
            }
            refs.append(ref)

        # S3: Use the Kaspa Generator to estimate the fee
        generator = Generator(
            network_id=network_id,  # type: ignore
            entries=refs,  # type: ignore
            outputs=[  # type: ignore
                {'address': source_address, 'amount': kaspa_to_sompi(send_amount)}
            ],
            priority_fee=kaspa_to_sompi(priority_fee),
            change_address=source_address,  # type: ignore
        )

        estimate: GeneratorSummary = generator.estimate()
        cli.success_table(
            title='Kaspa Fee Estimation Result',
            data=estimate.to_dict(),
        )
        """Sample output:
                                                    Kaspa Fee Estimation Result
        ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
        ┃ title                            ┃ value                                                            ┃
        ┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
        │ network_id                       │ mainnet                                                          │
        │ aggregated_utxos                 │ 1                                                                │
        │ aggregate_fees                   │ 223600                                                           │
        │ aggregate_mass                   │ 30089                                                            │
        │ number_of_generated_transactions │ 1                                                                │
        │ number_of_generated_stages       │ 1                                                                │
        │ final_transaction_amount         │ 50000000                                                         │
        │ final_transaction_id             │ 38a5e18bb3a563ad1ed4e9d0ba5f0c8a7433d1305562214435a7fa49ac9608a0 │
        └──────────────────────────────────┴──────────────────────────────────────────────────────────────────┘
        """

        """
        Result example:
            {
            networkType: 1,
            fees: 213600n,
            mass: 2036n,
            utxos: 1,
            finalTransactionId: '851d40a0336d5f34092b4011c798b6474db87f0b476945edd589ebf8ec824639',
            finalAmount: 2500000000n,
            transactions: 1
            }
        """

        return FeeEstimate(
            compute_mass=estimate.mass,
            storage_mass=0,
            network_mass=0,
            minimum_fee=estimate.fees,
            fee=estimate.fees,
            change=estimate.final_amount,  # type: ignore
            n_inputs=estimate.utxos,
            n_outputs=1,
        )
