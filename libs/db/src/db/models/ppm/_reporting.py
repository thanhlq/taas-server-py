"""PPM dashboards & reports (taas-specs/ppm/reporting/dashboards-reports-spec.md §3): daily project statistics
(trends, burnup / burndown — today's row rewritten until the day ends), dashboards (widget layout + filters, never
data) with their shares."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from advanced_alchemy.base import UUIDv7AuditBase
from advanced_alchemy.types import GUID
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from db.models.core.constants import ORGANIZATION_TABLE, TENANT_TABLE
from db.models.ews.constants import PROJECTS_ITERATIONS_TABLE, PROJECTS_TABLE

from .constants import (
    PPM_DASHBOARD_SHARES_TABLE,
    PPM_DASHBOARDS_TABLE,
    PPM_PROJECT_DAILY_STATS_TABLE,
)

DASHBOARD_SCOPES = ('personal', 'project', 'organization')
DASHBOARD_VISIBILITY = ('private', 'shared', 'scope')


def _tenant() -> Mapped[UUID]:
    return mapped_column(
        GUID(length=16),
        ForeignKey(f'{TENANT_TABLE}.id', ondelete='cascade'),
        nullable=False,
        index=True,
    )


def _organization() -> Mapped[UUID]:
    return mapped_column(
        GUID(length=16),
        ForeignKey(f'{ORGANIZATION_TABLE}.id', ondelete='cascade'),
        nullable=False,
        index=True,
    )


class PpmProjectDailyStats(UUIDv7AuditBase):
    """One project (or one of its iterations) × one UTC day: item counts and minutes (burnup, burndown, throughput)."""

    __tablename__ = PPM_PROJECT_DAILY_STATS_TABLE
    __table_args__ = (
        Index(
            'ux_taas_ppm_project_daily_stats_project',
            'project_id',
            'stats_date',
            unique=True,
            postgresql_where=text('iteration_id is null'),
        ),
        Index(
            'ux_taas_ppm_project_daily_stats_iteration',
            'iteration_id',
            'stats_date',
            unique=True,
            postgresql_where=text('iteration_id is not null'),
        ),
        Index('ix_taas_ppm_project_daily_stats_date', 'stats_date'),
    )

    tenant_id: Mapped[UUID] = _tenant()
    organization_id: Mapped[UUID] = _organization()
    project_id: Mapped[UUID] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{PROJECTS_TABLE}.id', ondelete='cascade'),
        nullable=False,
    )
    iteration_id: Mapped[UUID | None] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{PROJECTS_ITERATIONS_TABLE}.id', ondelete='cascade'),
        nullable=True,
    )
    """Null = the whole project."""
    stats_date: Mapped[date] = mapped_column(Date, nullable=False)
    items_total: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text('0')
    )
    items_done: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text('0')
    )
    items_open: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text('0')
    )
    items_overdue: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text('0')
    )
    items_added: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text('0')
    )
    items_completed: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text('0')
    )
    estimate_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text('0')
    )
    remaining_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text('0')
    )
    logged_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text('0')
    )
    billable_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text('0')
    )
    computed_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )


class PpmDashboard(UUIDv7AuditBase):
    """A named grid of widgets (``layout``) with default filters; ``scope_type`` personal · project · organization."""

    __tablename__ = PPM_DASHBOARDS_TABLE
    __table_args__ = (
        CheckConstraint(
            "scope_type in ('personal', 'project', 'organization')", name='scope_type'
        ),
        CheckConstraint(
            "visibility in ('private', 'shared', 'scope')", name='visibility'
        ),
        Index(
            'ix_taas_ppm_dashboards_scope', 'organization_id', 'scope_type', 'scope_id'
        ),
    )

    tenant_id: Mapped[UUID] = _tenant()
    organization_id: Mapped[UUID] = _organization()
    scope_type: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'personal'")
    )
    scope_id: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    """The project of a project dashboard (null otherwise)."""
    owner: Mapped[str] = mapped_column(String(320), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    layout: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    """``{schema_version, widgets: [{id, type, x, y, w, h, title, query, viz}]}`` — read and written as a whole."""
    filters: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'private'")
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text('1')
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )


class PpmDashboardShare(UUIDv7AuditBase):
    """A user who may view (or edit) a shared dashboard."""

    __tablename__ = PPM_DASHBOARD_SHARES_TABLE
    __table_args__ = (
        CheckConstraint("principal_type in ('user', 'role')", name='principal_type'),
        Index(
            'ux_taas_ppm_dashboard_shares_principal',
            'dashboard_id',
            'principal_type',
            'principal_id',
            unique=True,
        ),
    )

    tenant_id: Mapped[UUID] = _tenant()
    dashboard_id: Mapped[UUID] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{PPM_DASHBOARDS_TABLE}.id', ondelete='cascade'),
        nullable=False,
    )
    principal_type: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default=text("'user'")
    )
    principal_id: Mapped[str] = mapped_column(String(320), nullable=False)
    can_edit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text('false')
    )
