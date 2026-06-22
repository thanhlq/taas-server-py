"""
Kaspa fee estimator by using official Kaspa Wasm SDK: https://github.com/kaspanet/kaspa-python-sdk

See sample: https://github.com/kaspanet/kaspa-python-sdk/blob/main/examples/transactions/estimate.py
"""
from typing import Dict, Any
from platform_core import BaseService
from block_kaspa.kaspa_factory import KaspaFactory
from block_kaspa.client_rest import KaspaRestClient
from block_kaspa.types import UtxoModel, FeeEstimate, UtxoResponse
from block_kaspa import KaspaSettings
from kaspa import (
    Generator,
    PrivateKey,
    Resolver,
    RpcClient,
    kaspa_to_sompi,
    GeneratorSummary, UtxoEntries, UtxoEntryReference, UtxoEntry, TransactionOutpoint,
)

from platform_core.cli import cli

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

        # S1 count utxos for the source address
        count = await rest_client.count_utxos(source_address)
        if count > config.fee_estimator_max_utxos:
            self.logger.warning(
                f'Kaspa address {source_address} has {count} UTXOs, which exceeds the maximum limit of {config.fee_estimator_max_utxos}. Fee estimation may be inaccurate.'
            )

        _utxo_entries: list[UtxoResponse]  = (
            await rest_client.get_utxos(source_address)
        )

        print('--------')
        print(_utxo_entries)
        print('--------')

        refs: list[dict[str, Any]] = []
        for utxo in _utxo_entries:
            # outpoint=TransactionOutpoint(
            #             transaction_id=utxo.outpoint.transactionId,
            #             index=utxo.outpoint.index,
            #         )
            # entry=UtxoEntry(
            #         address=utxo.address,
            #         outpoint=outpoint,
            #         amount=utxo.utxoEntry.amount,
            #     )
            # ref_class = UtxoEntryReference(
            #     address=utxo.address,
            #     outpoint=TransactionOutpoint(
            #         transaction_id=utxo.outpoint.transactionId,
            #         index=utxo.outpoint.index,
            #     ),
            #     entry=UtxoEntry(
            #         amount=utxo.utxoEntry.amount,
            #         script_public_key=utxo.utxoEntry.scriptPublicKey.scriptPublicKey,
            #         block_daa_score=utxo.utxoEntry.blockDaaScore,
            #         is_coinbase=utxo.utxoEntry.isCoinbase,
            #     ),
            # )
            ref: dict[str, Any] =(
                {
                    "address": utxo.address,
                    "outpoint": {
                        "transaction_id": utxo.outpoint.transactionId,
                        "index": utxo.outpoint.index,
                    },
                    "entry": {
                        "amount": utxo.utxoEntry.amount,
                        "scriptPublicKey": {
                            "scriptPublicKey": utxo.utxoEntry.scriptPublicKey.scriptPublicKey
                        },
                        "blockDaaScore": utxo.utxoEntry.blockDaaScore,
                        "isCoinbase": utxo.utxoEntry.isCoinbase,
                    },
                }
            )
            refs.append(ref)

            print(f'Type of UTXO: {type(utxo)}, UTXO: {utxo}')


        generator = Generator(
            network_id=network_id,
            entries=UtxoEntries(items=refs),
            outputs=[
                {'address': source_address, 'amount': kaspa_to_sompi(send_amount)}
            ],
            priority_fee=kaspa_to_sompi(priority_fee),
            change_address=source_address,
        )

        estimate: GeneratorSummary = generator.estimate()
        print(estimate.final_transaction_id)

        for key, value in estimate.to_dict().items():
            cli.success_formal(key, value)

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
