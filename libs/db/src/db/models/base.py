import datetime
from uuid import UUID

from advanced_alchemy.base import AdvancedDeclarativeBase
from advanced_alchemy.types import DateTimeUTC
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, declarative_mixin, mapped_column, validates

# from advanced_alchemy.types import DateTimeUTC

type ID_COLUMN_TYPE = UUID



__all__ = [
    'SoftDeleteColumns',
    'AdvancedDeclarativeBase',
    'ID_COLUMN_TYPE',
    'JSONB',
]

@declarative_mixin
class SoftDeleteColumns:
    """Created/Updated At Fields Mixin."""

    deleted_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC(timezone=True),
        sort_order=3004,
    )

    @validates("deleted_at")
    def validate_tz_info(self, _: str, value: datetime.datetime) -> datetime.datetime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=datetime.UTC)
        return value
