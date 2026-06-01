from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from advanced_alchemy.base import UUIDv7Base
from sqlalchemy import TEXT, TIMESTAMP, ForeignKey, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from ..base import ID_COLUMN_TYPE, SoftDeleteColumns
from .constants import PAYROLL_TABLE, PAYRUN_TABLE, TIMELOG_TABLE


class Payrun(UUIDv7Base, SoftDeleteColumns):
    """Payrun"""

    __tablename__ = PAYRUN_TABLE

    payroll_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        ForeignKey(f'{PAYROLL_TABLE}.id'), nullable=True
    )
    sequence_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    user_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    timelog_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        ForeignKey(f'{TIMELOG_TABLE}.id'), nullable=True
    )
    timelog_date: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)
    period_from: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)
    period_to: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)
    pay_status: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    paycode_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    paycode_rate: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 6), nullable=True
    )
    payrate: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 6), nullable=True)
    total_log_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_log_hours: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    payment_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 6), nullable=True
    )
    currency_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
