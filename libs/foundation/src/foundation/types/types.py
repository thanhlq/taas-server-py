"""Contain so common types for foundation module."""

from enum import IntEnum


class SimpleStatus(IntEnum):
    """Simple status for foundation module."""

    ACTIVE = 1
    INACTIVE = 2
    SUSPENDED = 3
    CLOSED = 4
    ARCHIVED = 5
    DELETED = 6
