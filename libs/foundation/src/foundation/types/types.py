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


class AddressType(IntEnum):
    """Address type for foundation module."""

    HOME = 1
    WORK = 2
    OTHER = 3


class AddressFormat(IntEnum):
    """Address format for foundation module."""

    STREET = 1
    PO_BOX = 2
    APARTMENT = 3
    SUITE = 4
    OTHER = 5


class PhoneType(IntEnum):
    """Phone type for foundation module."""

    MOBILE = 1
    HOME = 2
    WORK = 3
    FAX = 4
    OTHER = 5


class PhoneFormat(IntEnum):
    """Phone format for foundation module."""

    INTERNATIONAL = 1
    NATIONAL = 2
    LOCAL = 3
    OTHER = 4


class EmailType(IntEnum):
    """Email type for foundation module."""

    PERSONAL = 1
    WORK = 2
    OTHER = 3


class EmailFormat(IntEnum):
    """Email format for foundation module."""

    PLAIN_TEXT = 1
    HTML = 2
    RICH_TEXT = 3
    OTHER = 4


class AddressStatus(IntEnum):
    """Address status for foundation module."""

    VERIFIED = 1
    UNVERIFIED = 2
    INVALID = 3
    OTHER = 4


class AddressPurpose(IntEnum):
    """Address purpose for foundation module."""

    BILLING = 1
    SHIPPING = 2
    MAILING = 3
    OTHER = 4


class PhoneStatus(IntEnum):
    """Phone status for foundation module."""

    VERIFIED = 1
    UNVERIFIED = 2
    INVALID = 3
    OTHER = 4


class PhonePurpose(IntEnum):
    """Phone purpose for foundation module."""

    PERSONAL = 1
    BUSINESS = 2
    EMERGENCY = 3
    OTHER = 4


class EmailStatus(IntEnum):
    """Email status for foundation module."""

    VERIFIED = 1
    UNVERIFIED = 2
    INVALID = 3
    OTHER = 4


class LegalEntityType(IntEnum):
    """Legal entity type for foundation module."""

    INDIVIDUAL = 1
    COMPANY = 2
    ORGANIZATION = 3
    """ What different vs company - organization is a broader term that can include companies, non-profits, government entities,
    and other types of legal entities. A company is a specific type of organization that is typically formed for profit and has
    shareholders or owners. In contrast, an organization can be any structured group of people working together for a common purpose,
    which may or may not be profit-driven. """
    GOVERNMENT = 4
    OTHER = 5


class Address:
    """Represents an address in the foundation module."""

    def __init__(
        self,
        *,
        line1: str,
        line2: str,
        city: str,
        state: str,
        postal_code: str,
        country: str,
        address_type: AddressType = AddressType.HOME,
    ):
        self.line1 = line1 # street address line 1
        self.line2 = line2 # suite, apartment, unit, building, floor, etc.
        self.city = city
        self.state = state
        self.postal_code = postal_code
        self.country = country
        self.address_type = address_type
