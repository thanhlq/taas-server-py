import datetime
from uuid import UUID

from advanced_alchemy.base import AdvancedDeclarativeBase
from advanced_alchemy.base import DefaultBase as BaseDBModel
from advanced_alchemy.mixins import SlugKey
from advanced_alchemy.types import DateTimeUTC
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, declarative_mixin, mapped_column, validates
from sqlalchemy.sql import text

# from advanced_alchemy.types import DateTimeUTC

type ID_COLUMN_TYPE = UUID
type TENANT_ID_COLUMN_TYPE = int


__all__ = [
    'SoftDeleteColumns',
    'AdvancedDeclarativeBase',
    'BaseDBModel',
    'ID_COLUMN_TYPE',
    'JSONB',
    'Uuid36DBGenerating',
    'SlugKey',
]


@declarative_mixin
class SoftDeleteColumns:
    """Created/Updated At Fields Mixin."""

    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTimeUTC(timezone=True),
        nullable=True,
        sort_order=3004,
    )

    @validates('deleted_at')
    def validate_tz_info(self, _: str, value: datetime.datetime | None) -> datetime.datetime | None:
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=datetime.UTC)
        return value


@declarative_mixin
class Uuid36DBGenerating:
    """
    UUID 36 (varchar) by using db generated value.
    Used for models as keycloak models which use gen_random_uuid() in db as default value for id column.
    """

    id: Mapped[str] = mapped_column(
        String(36),
        server_default=text('gen_random_uuid()'),
        primary_key=True,
    )
