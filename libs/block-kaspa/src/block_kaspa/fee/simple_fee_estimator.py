#!/usr/bin/env python3
"""
Kaspa transaction fee / mass calculator — pure Python, zero dependencies.

Given ONLY the UTXO records being spent and the amount to send, this computes
the transaction mass and the required fee, following the official specification:

  - Fees & mass overview : https://kaspa.aspectron.org/transactions/fees/index.html#mass-components
  - Storage mass (KIP-9) : https://github.com/kaspanet/kips/blob/master/kip-0009.md
  - Reference impl        : kaspanet/rusty-kaspa  consensus/core/src/mass/mod.rs
  - Python SDK            : https://github.com/kaspanet/kaspa-python-sdk

Model
-----
network_mass = max(compute_mass, storage_mass)        # spec: §mass-components
                                                      # relay/block limit mass,
                                                      # reported as `mass`.
fee = compute_mass * feerate + priority_fee           # the FEE is based on the
                                                      # COMPUTE mass only, not the
                                                      # network mass.

# Verified by running the WASM SDK Generator offline: the fee tracks compute_mass
# even when the network mass is storage-dominated. With no explicit feeRate the
# SDK applies a minimum feerate of 100 sompi/gram, so the demo tx pays:
#     3154 * 100 + priority(10000) = 325400   (matches the sample exactly)

compute_mass = size * MASS_PER_TX_BYTE
             + sum(2 + len(spk.script)) * MASS_PER_SCRIPT_PUB_KEY_BYTE
             + n_sigops * MASS_PER_SIG_OP

storage_mass (KIP-9):
  C = 10**12
  harmonic_outs = sum(C // out_value)
  relaxed when  |O| <= |I| <= 2   or   |O| == 1 :
      storage = max(0, harmonic_outs - sum(C // in_value))
  otherwise (standard) :
      storage = max(0, harmonic_outs - C * |I|**2 // sum(in_values))
"""
from block_kaspa.types import FeeEstimate

from dataclasses import dataclass
from math import ceil

# ── Consensus constants (rusty-kaspa, mainnet/testnet) ────────────────────────
MASS_PER_TX_BYTE = 1
MASS_PER_SCRIPT_PUB_KEY_BYTE = 10
MASS_PER_SIG_OP = 1000
STORAGE_MASS_PARAMETER = 10**12  # "C" in KIP-9

# Minimum feerate (sompi per gram of COMPUTE mass) the WASM SDK Generator applies
# when no explicit feeRate is given. Determined empirically by running the SDK.
MINIMUM_FEERATE = 100

# ── Serialized-size constants (transaction_estimated_serialized_size) ──────────
SUBNETWORK_ID_SIZE = 20
HASH_SIZE = 32
# Per input, when estimating an *unsigned* tx, the signature script is padded with
# a standard Schnorr signature: OP_DATA_65 (1) + 64-byte sig + 1-byte sighash = 66.
SIGNATURE_SCRIPT_SIZE = 66
SIG_OPS_PER_INPUT = 1  # standard P2PK / Schnorr input

# Fixed transaction overhead (everything except inputs and outputs):
#   version(2) + #inputs(8) + #outputs(8) + lockTime(8) + subnetworkId(20)
#   + gas(8) + payloadHash(32) + payloadLen(8)
_TX_FIXED_OVERHEAD = 2 + 8 + 8 + 8 + SUBNETWORK_ID_SIZE + 8 + HASH_SIZE + 8


def _input_serialized_size() -> int:
    # outpoint(32 txid + 4 index) + sigScriptLen(8) + sigScript + sequence(8)
    return 32 + 4 + 8 + SIGNATURE_SCRIPT_SIZE + 8


def _output_serialized_size(script_len_bytes: int) -> int:
    # amount(8) + scriptPublicKey.version(2) + scriptLen(8) + script
    return 8 + 2 + 8 + script_len_bytes


def transaction_serialized_size(
    n_inputs: int, output_script_lens: list[int], payload_len: int = 0
) -> int:
    size = _TX_FIXED_OVERHEAD + payload_len
    size += n_inputs * _input_serialized_size()
    size += sum(_output_serialized_size(s) for s in output_script_lens)
    return size


def compute_mass(
    n_inputs: int, output_script_lens: list[int], payload_len: int = 0
) -> int:
    """Compute mass = size mass + scriptPublicKey mass + sigop mass."""
    size = transaction_serialized_size(n_inputs, output_script_lens, payload_len)
    size_mass = size * MASS_PER_TX_BYTE
    spk_mass = sum(2 + s for s in output_script_lens) * MASS_PER_SCRIPT_PUB_KEY_BYTE
    sigops_mass = n_inputs * SIG_OPS_PER_INPUT * MASS_PER_SIG_OP
    return size_mass + spk_mass + sigops_mass


def storage_mass(input_amounts: list[int], output_amounts: list[int]) -> int:
    """Storage mass per KIP-9 (relaxed formula when |O| <= |I| <= 2 or |O| == 1)."""
    c = STORAGE_MASS_PARAMETER
    n_in, n_out = len(input_amounts), len(output_amounts)
    harmonic_outs = sum(c // o for o in output_amounts)

    if (n_out <= n_in <= 2) or n_out == 1:  # relaxed: harmonic of both sides
        harmonic_ins = sum(c // i for i in input_amounts)
        return max(0, harmonic_outs - harmonic_ins)

    # standard: harmonic outputs minus arithmetic-mean inputs
    arithmetic_ins = c * (n_in**2) // sum(input_amounts)
    return max(0, harmonic_outs - arithmetic_ins)





def _estimate_for(
    inputs: list[int],
    send_amount: int,
    feerate: float,
    priority_fee: int,
    output_script_len: int,
    payload_len: int,
) -> FeeEstimate:
    """Mass & fee for a FIXED input set (no selection). 2 outputs unless no change."""
    total_in = sum(inputs)
    n_in = len(inputs)

    n_outputs = 2
    cm = compute_mass(n_in, [output_script_len, output_script_len], payload_len)
    minimum_fee = ceil(cm * feerate)
    fee = minimum_fee + priority_fee
    change = total_in - send_amount - fee

    if change <= 0:  # no change output (exact spend or insufficient funds)
        n_outputs = 1
        cm = compute_mass(n_in, [output_script_len], payload_len)
        minimum_fee = ceil(cm * feerate)
        fee = minimum_fee + priority_fee
        change = total_in - send_amount - fee  # negative => insufficient

    outputs = [send_amount, change] if n_outputs == 2 else [send_amount]
    sm = storage_mass(inputs, outputs)
    return FeeEstimate(cm, sm, max(cm, sm), minimum_fee, fee, change, n_in, n_outputs)


def estimate_fee(
    utxo_amounts: list[int],
    send_amount: int,
    *,
    feerate: float = MINIMUM_FEERATE,
    priority_fee: int = 0,
    output_script_len: int = 34,  # P2PK script: 0x20 + 32-byte key + 0xac
    payload_len: int = 0,
    select_utxos: bool = True,
) -> FeeEstimate:
    """
    Estimate mass & fee from a UTXO set and a send amount, mirroring the WASM SDK.

    Coin selection (select_utxos=True): consume UTXOs smallest-first (the order the
    SDK / demo uses) until the selection BOTH covers `send + fee` AND has
    `storage_mass <= compute_mass`. The second condition is why a small send keeps
    consuming inputs: a single input against a small output yields a large storage
    mass, so the SDK keeps adding inputs (which lowers storage mass via KIP-9).

    With select_utxos=False every supplied UTXO is treated as an input.
    """
    if not utxo_amounts:
        raise ValueError('no utxos provided')

    amounts = sorted(utxo_amounts) if select_utxos else list(utxo_amounts)

    selected: list[int] = []
    result = _estimate_for(
        amounts, send_amount, feerate, priority_fee, output_script_len, payload_len
    )
    for amt in amounts:
        selected.append(amt)
        result = _estimate_for(
            selected, send_amount, feerate, priority_fee, output_script_len, payload_len
        )
        if not select_utxos:
            continue
        covered = sum(selected) >= send_amount + result.fee
        if covered and result.storage_mass <= result.compute_mass:
            break
    return result


__all__ = ['estimate_fee', 'FeeEstimate']
