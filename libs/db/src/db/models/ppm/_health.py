"""Project health (taas-specs/ppm/health/project-health-spec.md §3): daily snapshots of the six dimensions and the
overall rating (today's row rewritten on each recompute, past rows frozen), manual overrides (≤ 1 active per project,
kept for audit) and health policies (organization default + project exceptions)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from advanced_alchemy.base import UUIDv7AuditBase
from advanced_alchemy.types import GUID
from sqlalchemy import (
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
from db.models.ews.constants import PROJECTS_TABLE

from .constants import (
    PPM_HEALTH_OVERRIDES_TABLE,
    PPM_HEALTH_POLICIES_TABLE,
    PPM_HEALTH_SNAPSHOTS_TABLE,
)

HEALTH_RATINGS = ('green', 'amber', 'red', 'none')
HEALTH_DIMENSIONS = ('schedule', 'budget', 'resources', 'scope', 'quality', 'risk')
_RATING_CHECK = "in ('green', 'amber', 'red', 'none')"


class PpmHealthSnapshot(UUIDv7AuditBase):
    """One project × one day: ratings (columns, for portfolio filters), reasons and the metrics they came from."""

    __tablename__ = PPM_HEALTH_SNAPSHOTS_TABLE
    __table_args__ = (
        *(
            CheckConstraint(f'{d} {_RATING_CHECK}', name=d)
            for d in (*HEALTH_DIMENSIONS, 'overall', 'overall_effective')
        ),
        Index(
            'ux_taas_ppm_health_snapshots_day',
            'project_id',
            'snapshot_date',
            unique=True,
        ),
        Index('ix_taas_ppm_health_snapshots_date', 'snapshot_date'),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{TENANT_TABLE}.id', ondelete='cascade'),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[UUID] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{ORGANIZATION_TABLE}.id', ondelete='cascade'),
        nullable=False,
        index=True,
    )
    project_id: Mapped[UUID] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{PROJECTS_TABLE}.id', ondelete='cascade'),
        nullable=False,
    )
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    schedule: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default=text("'none'")
    )
    budget: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default=text("'none'")
    )
    resources: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default=text("'none'")
    )
    scope: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default=text("'none'")
    )
    quality: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default=text("'none'")
    )
    risk: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default=text("'none'")
    )
    overall: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default=text("'none'")
    )
    overall_effective: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default=text("'none'")
    )
    override_id: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    reasons: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    """``{dimension: [{rule, rating, code, params, evidence}]}``."""
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    policy_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text('0')
    )
    computed_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )


class PpmHealthOverride(UUIDv7AuditBase):
    """A manual overall rating with a reason and an expiry (§5.9)."""

    __tablename__ = PPM_HEALTH_OVERRIDES_TABLE
    __table_args__ = (
        CheckConstraint("rating in ('green', 'amber', 'red')", name='rating'),
        CheckConstraint("status in ('active', 'expired', 'cleared')", name='status'),
        Index(
            'ux_taas_ppm_health_overrides_active',
            'project_id',
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{TENANT_TABLE}.id', ondelete='cascade'),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[UUID] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{ORGANIZATION_TABLE}.id', ondelete='cascade'),
        nullable=False,
        index=True,
    )
    project_id: Mapped[UUID] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{PROJECTS_TABLE}.id', ondelete='cascade'),
        nullable=False,
    )
    rating: Mapped[str] = mapped_column(String(8), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    expires_on: Mapped[date] = mapped_column(Date, nullable=False)
    set_by: Mapped[str] = mapped_column(String(320), nullable=False)
    cleared_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
    cleared_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default=text("'active'")
    )


class PpmHealthPolicy(UUIDv7AuditBase):
    """Thresholds + enabled dimensions of an organization (``project_id`` null) or of one project (exception)."""

    __tablename__ = PPM_HEALTH_POLICIES_TABLE
    __table_args__ = (
        Index(
            'ux_taas_ppm_health_policies_org',
            'organization_id',
            unique=True,
            postgresql_where=text('project_id is null'),
        ),
        Index('ux_taas_ppm_health_policies_project', 'project_id', unique=True),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{TENANT_TABLE}.id', ondelete='cascade'),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[UUID] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{ORGANIZATION_TABLE}.id', ondelete='cascade'),
        nullable=False,
    )
    project_id: Mapped[UUID | None] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{PROJECTS_TABLE}.id', ondelete='cascade'),
        nullable=True,
    )
    thresholds: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    dimensions: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    """Enabled dimensions (null = all)."""
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text('1')
    )
