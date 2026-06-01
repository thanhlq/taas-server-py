import datetime
from uuid import UUID

from advanced_alchemy.base import AdvancedDeclarativeBase
from advanced_alchemy.types import DateTimeUTC
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, declarative_mixin, mapped_column

type ID_COLUMN_TYPE = UUID


@declarative_mixin
class SoftDeleteColumns:
    """Soft Delete Fields Mixin."""

    """Date/time of instance deletion."""
    deleted_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC(timezone=True),
        default=lambda: datetime.datetime.now(datetime.UTC),
        onupdate=lambda: datetime.datetime.now(datetime.UTC),
        sort_order=3004,
    )


__all__ = [
    'SoftDeleteColumns',
    'AdvancedDeclarativeBase',
    'ID_COLUMN_TYPE',
    'JSONB',
]
