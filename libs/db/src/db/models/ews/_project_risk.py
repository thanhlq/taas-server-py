from __future__ import annotations

from typing import Optional

from advanced_alchemy.base import UUIDv7Base
from sqlalchemy import TEXT, ForeignKey, Integer, text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import ID_COLUMN_TYPE, SoftDeleteColumns
from ..types import PROJECTS_RISKS_TABLE, PROJECTS_TABLE


class ProjectRisk(UUIDv7Base, SoftDeleteColumns):
    """Project Risks"""

    __tablename__ = PROJECTS_RISKS_TABLE

    project_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        ForeignKey(f'{PROJECTS_TABLE}.id'), nullable=True
    )
    risk_source: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    risk_mitigation_plan: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    risk_status: Mapped[Optional[str]] = mapped_column(
        TEXT, nullable=True, server_default=text("'new'::character")
    )
    probability: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    impact: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    probability_value: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    impact_value: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    impact_cost: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    impact_schedule: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    impact_performance: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    risk_result: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
