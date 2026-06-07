"""Common value objects."""

from decimal import Decimal
from enum import StrEnum

from platform_core.models import ValueObject
from platform_core.utils.validation import ValidationError


class Currency(StrEnum):
    """Currency enumeration."""

    USD = 'USD'
    EUR = 'EUR'
    GBP = 'GBP'
    BTC = 'BTC'
    ETH = 'ETH'


class Amount(ValueObject):
    """Money amount value object."""

    value: Decimal
    currency: Currency

    def __init__(self, value: float | Decimal | str, currency: Currency, **data):
        """Initialize amount with validation."""
        decimal_value: Decimal
        if isinstance(value, (float, str)):
            decimal_value = Decimal(str(value))
        else:
            decimal_value = value  # type: ignore

        if decimal_value < 0:
            raise ValidationError('Amount cannot be negative')

        self.value = decimal_value
        self.currency = currency

    def add(self, other: 'Amount') -> 'Amount':
        """Add two amounts of the same currency."""
        if self.currency != other.currency:
            raise ValidationError(
                f'Cannot add different currencies: {self.currency} and {other.currency}'
            )
        return Amount(value=self.value + other.value, currency=self.currency)

    def subtract(self, other: 'Amount') -> 'Amount':
        """Subtract two amounts of the same currency."""
        if self.currency != other.currency:
            raise ValidationError(
                f'Cannot subtract different currencies: {self.currency} and {other.currency}'
            )
        result_value = self.value - other.value
        if result_value < 0:
            raise ValidationError('Result cannot be negative')
        return Amount(value=result_value, currency=self.currency)

    def multiply(self, factor: float | Decimal) -> 'Amount':
        """Multiply amount by a factor."""
        if isinstance(factor, float):
            factor = Decimal(str(factor))
        result_value = self.value * factor
        if result_value < 0:
            raise ValidationError('Result cannot be negative')
        return Amount(value=result_value, currency=self.currency)

    def is_zero(self) -> bool:
        """Check if amount is zero."""
        return self.value == 0

    def __str__(self) -> str:
        """String representation of amount."""
        return f'{self.value:.2f} {self.currency}'
