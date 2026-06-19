from dataclasses import dataclass


@dataclass
class FeeEstimate:
    compute_mass: int
    storage_mass: int
    network_mass: int  # max(compute, storage) -- relay/block limit mass (`mass`)
    minimum_fee: int  # compute_mass * feerate (no priority)
    fee: int  # minimum_fee + priority_fee
    change: int
    n_inputs: int
    n_outputs: int
