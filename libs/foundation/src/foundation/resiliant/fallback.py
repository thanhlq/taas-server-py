"""
Fallback primitive.

Runs a primary async handler and, on a configured exception, invokes a
fallback handler instead.

Layout:

* `FallbackConfig`   - policy
* `FallbackService`  - primary -> fallback dispatcher
* `FallbackFactory`  - DI helper
"""

from __future__ import annotations

import msgspec

# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class FallbackError(Exception):
    """Raised when both primary and fallback fail."""

    def __init__(self, primary: BaseException, fallback: BaseException) -> None:
        super().__init__(f"Primary failed: {primary!r}; fallback failed: {fallback!r}")
        self.primary = primary
        self.fallback = fallback


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #


class FallbackConfig(msgspec.Struct, frozen=True):
    """Policy for the fallback service."""

    # Exception types that trigger the fallback. Default: all `Exception`s.
    fallback_on: tuple[type[BaseException], ...] = (Exception,)


__all__ = [
    "FallbackConfig",
    "FallbackError",
]
