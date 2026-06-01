from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from advanced_alchemy.base import UUIDv7Base
from sqlalchemy import TEXT, TIMESTAMP, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from ..base import SoftDeleteColumns
from ..types import PAYRATES_ADJUSTMENTS_TABLE


class PayrateAdjustment(UUIDv7Base, SoftDeleteColumns):
    """Payrate Adjustment"""

    __tablename__ = PAYRATES_ADJUSTMENTS_TABLE

    user_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    effective_date: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)
    payrate: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 6), nullable=True)
    currency_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    site_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    work_type_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    work_activity_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
