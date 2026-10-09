"""Platform notifications (taas-specs/ppm/automation/automation-spec.md §3, Part A; ADR-24): one in-app inbox for
every app (``app`` column), deliveries per channel (e-mail today), preferences per user × kind × channel and personal
delivery settings (time zone, digest, quiet hours). App-agnostic: apps notify through ``ews.notifications``.

Recipients are IAM users (``recipient_user_id``) with their e-mail at notification time (``recipient_email``) — the
e-mail also matches recipients known only by e-mail (PPM ids / e-mails, ADR-12).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from advanced_alchemy.base import UUIDv7AuditBase
from advanced_alchemy.types import GUID, DateTimeUTC
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from db.models.base import JSONB
from db.models.core.constants import TENANT_TABLE

from .constants import (
    NOTIFICATION_DELIVERIES_TABLE,
    NOTIFICATION_PREFERENCES_TABLE,
    NOTIFICATION_USER_SETTINGS_TABLE,
    NOTIFICATIONS_TABLE,
)


def _tenant_fk() -> Mapped[UUID]:
    return mapped_column(
        GUID(length=16),
        ForeignKey(f'{TENANT_TABLE}.id', ondelete='cascade'),
        nullable=False,
        index=True,
    )


class Notification(UUIDv7AuditBase):
    """One in-app notification of one recipient (Ppm-1703). ``dedup_key`` makes deliveries idempotent (Ppm-1711),
    ``group_key`` batches repeats within 10 minutes into one row (``count``, Ppm-1710)."""

    __tablename__ = NOTIFICATIONS_TABLE
    __table_args__ = (
        Index('ux_taas_notifications_dedup', 'dedup_key', unique=True),
        Index(
            'ix_taas_notifications_recipient',
            'recipient_user_id',
            'read_at',
            text('created_at DESC'),
        ),
        Index(
            'ix_taas_notifications_recipient_email',
            'recipient_email',
            'read_at',
            text('created_at DESC'),
        ),
        Index('ix_taas_notifications_group', 'group_key', text('created_at DESC')),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    organization_id: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    recipient_user_id: Mapped[UUID | None] = mapped_column(
        GUID(length=16), nullable=True
    )
    recipient_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    app: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    """``<app>:<kind>``, e.g. ``ppm:task_assigned``."""
    subject_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    subject_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    project_id: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    link: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    """Path inside the web app, relative to the organization: ``/ppm/projects/<id>?task=<taskId>``."""
    actor_ref: Mapped[str | None] = mapped_column(String(320), nullable=True)
    actor_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    via: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'user'")
    )
    group_key: Mapped[str | None] = mapped_column(String(400), nullable=True)
    count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text('1')
    )
    dedup_key: Mapped[str] = mapped_column(String(400), nullable=False)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(
        DateTimeUTC(timezone=True), nullable=True
    )


class NotificationDelivery(UUIDv7AuditBase):
    """A notification sent on a channel other than in-app (e-mail now; digest, push later) — Ppm-1704, Ppm-1714."""

    __tablename__ = NOTIFICATION_DELIVERIES_TABLE
    __table_args__ = (
        CheckConstraint(
            "status in ('pending', 'deferred', 'sent', 'failed', 'bounced', 'suppressed')",
            name='status',
        ),
        Index(
            'ix_taas_notification_deliveries_due',
            'scheduled_for',
            postgresql_where=text("status in ('pending', 'deferred')"),
        ),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    notification_id: Mapped[UUID] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{NOTIFICATIONS_TABLE}.id', ondelete='cascade'),
        nullable=False,
        index=True,
    )
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    """``email`` · ``digest``."""
    recipient_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    scheduled_for: Mapped[datetime] = mapped_column(
        DateTimeUTC(timezone=True), nullable=False, server_default=text('now()')
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text('0')
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTimeUTC(timezone=True), nullable=True
    )
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)


class NotificationPreference(UUIDv7AuditBase):
    """``mode`` (``instant`` · ``digest`` · ``off``) of one user for one kind (or ``*``) and channel (Ppm-1706)."""

    __tablename__ = NOTIFICATION_PREFERENCES_TABLE
    __table_args__ = (
        CheckConstraint("mode in ('instant', 'digest', 'off')", name='mode'),
        Index(
            'ux_taas_notification_preferences_user',
            'user_id',
            'app',
            'kind',
            'channel',
            unique=True,
        ),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    user_id: Mapped[UUID] = mapped_column(GUID(length=16), nullable=False)
    app: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    mode: Mapped[str] = mapped_column(String(8), nullable=False)


class NotificationUserSettings(UUIDv7AuditBase):
    """Delivery settings of one user: time zone, digest (Ppm-1705), quiet hours (Ppm-1709)."""

    __tablename__ = NOTIFICATION_USER_SETTINGS_TABLE
    __table_args__ = (
        CheckConstraint("digest in ('daily', 'weekly', 'off')", name='digest'),
        Index('ux_taas_notification_user_settings_user', 'user_id', unique=True),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    user_id: Mapped[UUID] = mapped_column(GUID(length=16), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    time_zone: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text("'UTC'")
    )
    digest: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default=text("'daily'")
    )
    digest_hour: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text('8')
    )
    quiet_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """Hour 0–23 (user time zone) from which instant e-mails wait; ``None`` = no quiet hours."""
    quiet_to: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quiet_weekends: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text('false')
    )
    next_digest_at: Mapped[datetime | None] = mapped_column(
        DateTimeUTC(timezone=True), nullable=True
    )
