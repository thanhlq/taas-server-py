from dataclasses import dataclass
from typing import Dict, Optional, Literal
from ..security.key_types import KeyType

AddressFormat = Literal[
    'evm-hex',  # 0x + last 20 bytes of Keccak-256
    'base58',  # Base58 (Solana) / Base58Check
    'bech32',  # Bech32/Bech32m (Cosmos, Bitcoin SegWit/Taproot)
    'ss58',  # Substrate SS58
    'stark-hex',  # Starknet smart contract address
]


@dataclass(frozen=True)
class ChainAddressSpec:
    chain_name: str
    key_type: KeyType
    format: AddressFormat
    prefix: Optional[str] = None
    example_address: str = ''


CHAIN_ADDRESS_MAP: Dict[str, ChainAddressSpec] = {
    'ethereum': ChainAddressSpec(
        chain_name='Ethereum (EVM)',
        key_type=KeyType.SECP256K1,
        format='evm-hex',
        example_address='0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045',
    ),
    'bitcoin': ChainAddressSpec(
        chain_name='Bitcoin (Native SegWit / Taproot)',
        key_type=KeyType.SECP256K1_SCHNORR,
        format='bech32',
        prefix='bc',
        example_address='bc1p5d86063bh09sp8d2pt290p95m24g3ut42re5223chjp9439x54qsch82ch',
    ),
    'solana': ChainAddressSpec(
        chain_name='Solana',
        key_type=KeyType.ED25519,
        format='base58',
        example_address='7Vx8sS5Kz1WJ3B2aM1S9R82kA4oZ9qXyW21P30191aa',
    ),
    'cosmos': ChainAddressSpec(
        chain_name='Cosmos Hub',
        key_type=KeyType.SECP256K1,
        format='bech32',
        prefix='cosmos',
        example_address='cosmos1dep894nvfv9w2xy2kgdygjrsqtzq2n0yrf2493p',
    ),
    'polkadot': ChainAddressSpec(
        chain_name='Polkadot',
        key_type=KeyType.SR25519,
        format='ss58',
        prefix='0',
        example_address='1FRMM8PEiWXYax7rpS6X4XZX1aAAzSWRRPAwjBnkqBmCJ4p',
    ),
    'starknet': ChainAddressSpec(
        chain_name='Starknet',
        key_type=KeyType.STARK,
        format='stark-hex',
        example_address='0x0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',
    ),
}


def get_address_spec(chain: str) -> ChainAddressSpec:
    """Retrieves the address format and key specification for a given chain."""
    try:
        return CHAIN_ADDRESS_MAP[chain.lower()]
    except KeyError:
        raise ValueError(f'Unsupported chain address specification: {chain}')
