"""
Timeout primitive.

Caps the wall-clock duration of an async handler. Stateless.

Layout:

* `TimeoutConfig`   - policy
* `TimeoutService`  - executes a handler under a deadline
* `TimeoutFactory`  - DI helper
"""

from __future__ import annotations

import msgspec

# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class TimeoutError_(Exception):
    """Raised when a handler exceeds its deadline."""

    def __init__(self, seconds: float) -> None:
        super().__init__(f"Operation exceeded timeout of {seconds}s")
        self.seconds = seconds


# Public alias keeps the conventional name without shadowing builtins at module scope.
OperationTimeoutError = TimeoutError_


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #


class TimeoutConfig(msgspec.Struct, frozen=True):
    """Policy for the timeout service."""

    seconds: float = 5.0


__all__ = [
    "OperationTimeoutError",
    "TimeoutConfig",
]
