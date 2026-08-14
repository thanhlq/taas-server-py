from enum import StrEnum
from typing import Literal


class KeyType(StrEnum):
    # --- ECDSA / secp256k1 family (Bitcoin, Ethereum, EVM, Cosmos, Tron) ---
    SECP256K1 = 'secp256k1'  # ECDSA — threshold-signable (GG20/CGGMP)
    SECP256K1_SCHNORR = 'secp256k1-schnorr'  # BIP340 / Taproot

    # --- EdDSA / Edwards curves (Solana, Aptos, Sui, Near, Cardano, Stellar, TON) ---
    ED25519 = 'ed25519'  # EdDSA — threshold-signable (FROST)
    ED25519_BLAKE2B = 'ed25519-blake2b'  # Nano and a few others

    # --- NIST / P-curves (passkeys, WebAuthn, some enterprise chains) ---
    SECP256R1 = 'secp256r1'  # aka P-256 / prime256v1
    SECP384R1 = 'secp384r1'  # aka P-384
    SECP521R1 = 'secp521r1'  # aka P-521

    # --- Substrate / Polkadot ---
    SR25519 = 'sr25519'  # Schnorrkel/Ristretto — Substrate default

    # --- Key agreement (ECDH), not signing ---
    X25519 = 'x25519'  # Curve25519 ECDH

    # --- Pairing-friendly (Eth2 consensus, Chia, Filecoin) ---
    BLS12381_G1 = 'bls12-381-g1'
    BLS12381_G2 = 'bls12-381-g2'

    # --- StarkNet ---
    STARK = 'stark'  # Stark-friendly curve


KeyTypeT = Literal[
    # ECDSA / secp256k1
    'secp256k1',
    'secp256k1-schnorr',
    # EdDSA
    'ed25519',
    'ed25519-blake2b',
    # NIST / P-curves
    'secp256r1',
    'secp384r1',
    'secp521r1',
    # Substrate
    'sr25519',
    # ECDH
    'x25519',
    # BLS
    'bls12-381-g1',
    'bls12-381-g2',
    # StarkNet
    'stark',
]
