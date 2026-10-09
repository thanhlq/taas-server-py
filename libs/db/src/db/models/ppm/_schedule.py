"""PPM schedule (taas-specs/ppm/schedule/schedule-spec.md §3): phases of a project's plan (Ppm-1001…1003) and work
item links — dependencies FS · SS · FF · SF with lag in working days and the non-scheduling relations ``relates`` ·
``duplicates`` · ``blocks`` (Ppm-1020…1025, ADR-14)."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from advanced_alchemy.base import UUIDv7AuditBase
from advanced_alchemy.types import GUID
from sqlalchemy import CheckConstraint, Date, Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from db.models.base import SoftDeleteColumns
from db.models.core.constants import ORGANIZATION_TABLE, TENANT_TABLE
from db.models.ews.constants import PROJECTS_TABLE, TASKS_TABLE

from .constants import PPM_PHASES_TABLE, PPM_WORK_ITEM_LINKS_TABLE

LINK_TYPES = ('fs', 'ss', 'ff', 'sf', 'relates', 'duplicates', 'blocks')
DEPENDENCY_TYPES = ('fs', 'ss', 'ff', 'sf')


class PpmPhase(UUIDv7AuditBase, SoftDeleteColumns):
    """An ordered stage of a project's plan; groups top-level items (subtasks inherit). Deleting it clears
    ``phase_id`` on its items."""

    __tablename__ = PPM_PHASES_TABLE
    __table_args__ = (Index('ix_taas_ppm_phases_project', 'project_id', 'position'),)

    tenant_id: Mapped[UUID] = mapped_column(
        GUID(length=16), ForeignKey(f'{TENANT_TABLE}.id', ondelete='cascade'), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        GUID(length=16), ForeignKey(f'{PROJECTS_TABLE}.id', ondelete='cascade'), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    position: Mapped[float] = mapped_column(Float, nullable=False, server_default=text('0'))
    planned_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    planned_finish: Mapped[date | None] = mapped_column(Date, nullable=True)


class PpmWorkItemLink(UUIDv7AuditBase, SoftDeleteColumns):
    """A typed link from a source (predecessor) to a target (successor) item of one organization."""

    __tablename__ = PPM_WORK_ITEM_LINKS_TABLE
    __table_args__ = (
        CheckConstraint(
            "type in ('fs', 'ss', 'ff', 'sf', 'relates', 'duplicates', 'blocks')", name='type'
        ),
        CheckConstraint('source_task_id <> target_task_id', name='not_self'),
        Index(
            'ux_taas_ppm_work_item_links_pair',
            text('least(source_task_id, target_task_id)'),
            text('greatest(source_task_id, target_task_id)'),
            unique=True,
            postgresql_where=text("deleted_at is null and type in ('fs', 'ss', 'ff', 'sf')"),
        ),
        Index('ix_taas_ppm_work_item_links_target', 'target_task_id'),
        Index('ix_taas_ppm_work_item_links_source', 'source_task_id'),
        Index('ix_taas_ppm_work_item_links_project', 'source_project_id'),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        GUID(length=16), ForeignKey(f'{TENANT_TABLE}.id', ondelete='cascade'), nullable=False, index=True
    )
    organization_id: Mapped[UUID] = mapped_column(
        GUID(length=16), ForeignKey(f'{ORGANIZATION_TABLE}.id', ondelete='cascade'), nullable=False
    )
    source_task_id: Mapped[UUID] = mapped_column(
        GUID(length=16), ForeignKey(f'{TASKS_TABLE}.id', ondelete='cascade'), nullable=False
    )
    target_task_id: Mapped[UUID] = mapped_column(
        GUID(length=16), ForeignKey(f'{TASKS_TABLE}.id', ondelete='cascade'), nullable=False
    )
    source_project_id: Mapped[UUID] = mapped_column(GUID(length=16), nullable=False)
    target_project_id: Mapped[UUID] = mapped_column(GUID(length=16), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'fs'"))
    lag_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('0'))
    created_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
