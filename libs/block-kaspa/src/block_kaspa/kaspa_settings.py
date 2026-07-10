from __future__ import annotations

from dataclasses import dataclass, field

from foundation.utils.env_utils import get_env

# KASPA_TESTNET_NETWORK_ID = 'testnet-10'
KASPA_MAINNET_NETWORK_ID = 'mainnet'

KASPA_TESTNET_REST_API_URL = 'https://api-tn10.kaspa.org'
KASPA_MAINNET_REST_API_URL = 'https://api.kaspa.org'


KASPA_ESTIMATED_NETWORK_FEE: int = 316500 # in sompi


MAX_UTXOS = 1000
""" The maximum number of UTXOs to fetch from the Kaspa node for a given address.
    This is a safeguard to prevent excessive data retrieval and processing, which could
    lead to performance issues or timeouts. If an address has more than this number of
    UTXOs, the fee estimation process will raise an exception, prompting the user to
    manually select UTXOs or reduce the number of UTXOs in their wallet.
"""


@dataclass
class KaspaSettings:
    """Kaspa configuration (user-defined settings, e.g. from environment)."""

    debug: bool = field(default_factory=get_env('KASPA_DEBUG', False, bool))
    """ Debug Kaspa blockchain """

    network_id: str = field(
        default_factory=get_env('KASPA_NETWORK', None, str)
    )

    rpc_url: str | None = field(default_factory=get_env('KASPA_RPC_URL', None, str))
    rpc_user: str | None = field(default_factory=get_env('KASPA_RPC_USER', None, str))
    rpc_password: str | None = field(
        default_factory=get_env('KASPA_RPC_PASSWORD', None, str)
    )

    rest_url: str = field(default_factory=get_env('KASPA_REST_URL', None, str))
    rest_api_key: str | None = field(
        default_factory=get_env('KASPA_REST_API_KEY', None, str)
    )
    rest_api_key_header_name: str | None = field(
        default_factory=get_env('KASPA_REST_API_KEY_HEADER_NAME', 'api-key', str)
    )

    fee_estimator_max_utxos: int = field(
        default_factory=get_env('KASPA_FEE_ESTIMATOR_MAX_UTXOS', MAX_UTXOS, int)
    )
    fee_estimator_fallback_feerate: int = field(
        default_factory=get_env(
            'KASPA_FEE_ESTIMATOR_FALLBACK_FEERATE', KASPA_ESTIMATED_NETWORK_FEE, int
        )
    )

    def __post_init__(self) -> None:
        if not self.network_id:
            raise ValueError('KASPA_NETWORK environment variable is required but not set.')

        # Default the REST URL to the network-appropriate public endpoint when unset.
        if not self.rest_url:
            self.rest_url = (
                KASPA_TESTNET_REST_API_URL
                if self.network_id == KASPA_TESTNET_NETWORK_ID
                else KASPA_MAINNET_REST_API_URL
            )

        self.fee_estimator_fallback_feerate = (
            self.fee_estimator_fallback_feerate or KASPA_ESTIMATED_NETWORK_FEE
        )
        # check if not float, then convert str to float
        if not isinstance(self.fee_estimator_fallback_feerate, int):
            print(
                f'KaspaSettings: fee_estimator_fallback_feerate is not float, converting to float: {self.fee_estimator_fallback_feerate}'
            )
            self.fee_estimator_fallback_feerate = int(
                self.fee_estimator_fallback_feerate
            )
