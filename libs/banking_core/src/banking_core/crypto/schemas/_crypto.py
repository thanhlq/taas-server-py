from typing import Any

import msgspec
from foundation.serialization import BaseModel

required_fields = [
    'name',
    'symbol',
    'blockchain',
    'network',
    'type',
    'decimals',
    'short_name',
]


class CryptoToken(BaseModel):
    name: str
    symbol: str
    blockchain: str
    network: str
    type: str
    decimals: int
    short_name: str

    contract_address: str | None = None
    treasury_account: str | None = None
    token_id: str | None = None
    internal_token: str | None = None
    char_symbol: str | None = None
    icon: str | None = None
    color: str | None = None
    priority: int | None = None
    erc20_permit_supported: bool | None = None
    erc20_permit_eip712_domain: list[dict[str, Any]] | None = None
    erc20_permit_contract_domain: dict[str, Any] | None = None
    enabled: bool | None = None
    token_icon_url: str | None = None
    blockchain_icon_url: str | None = None
    show_blockchain_icon: bool | None = False
    restrict_to_whitelist: bool | None = False
    compliance_enabled: bool | None = False
    delisted: bool | None = False
    is_stable_coin: bool = False
    chain_id: int | None = None
    categories: list[str] = msgspec.field(default_factory=lambda: ['CRYPTO'])
    """ CRYPTO or FIAT or NFT or OTHER """
    token_sale_term_required: bool | None = None

    def validate(self) -> None:
        for field in required_fields:
            if getattr(self, field) is None:
                raise ValueError(f'{field} is a required field and cannot be None.')

    def __post_init__(self):
        pass
