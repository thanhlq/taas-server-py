from __future__ import annotations

from dataclasses import dataclass, field

from platform_core.utils.env_utils import get_env

KASPA_TESTNET_NETWORK_ID = 'testnet-10'
KASPA_MAINNET_NETWORK_ID = 'mainnet'

KASPA_TESTNET_REST_API_URL = 'https://api-tn10.kaspa.org'
KASPA_MAINNET_REST_API_URL = 'https://api.kaspa.org'


@dataclass
class KaspaSettings:
    """Kaspa configuration (user-defined settings, e.g. from environment)."""

    network_id: str = field(
        default_factory=get_env('KASPA_NETWORK_ID', KASPA_TESTNET_NETWORK_ID, str)
    )

    rpc_url: str | None = field(default_factory=get_env('KASPA_RPC_URL', None, str))
    rpc_user: str | None = field(default_factory=get_env('KASPA_RPC_USER', None, str))
    rpc_password: str | None = field(default_factory=get_env('KASPA_RPC_PASSWORD', None, str))

    rest_url: str = field(default_factory=get_env('KASPA_REST_URL', None, str))
    rest_api_key: str | None = field(default_factory=get_env('KASPA_REST_API_KEY', None, str))
    rest_api_key_header_name: str | None = field(default_factory=get_env('KASPA_REST_API_KEY_HEADER_NAME', 'api-key', str))

    def __post_init__(self) -> None:
        # Default the REST URL to the network-appropriate public endpoint when unset.
        if not self.rest_url:
            self.rest_url = (
                KASPA_TESTNET_REST_API_URL
                if self.network_id == KASPA_TESTNET_NETWORK_ID
                else KASPA_MAINNET_REST_API_URL
            )
