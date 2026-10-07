"""Media library (app ``media``): folders, assets, per-user favorites and usages by other apps.

Files live in the tenant bucket under ``media/<organization_id>/<asset_id>/…`` (``@taas/blob-service``);
documents (PDF, office files, …) belong to the Documents app (``documents/`` prefix), not here.
Spec: taas-specs/media/media-app-spec.md.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from advanced_alchemy.base import UUIDv7AuditBase
from advanced_alchemy.types import GUID, DateTimeUTC
from sqlalchemy import (
    BigInteger,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from db.models.base import JSONB, SoftDeleteColumns
from db.models.core.constants import ORGANIZATION_TABLE, TENANT_TABLE

from .constants import (
    MEDIA_ASSETS_TABLE,
    MEDIA_FAVORITES_TABLE,
    MEDIA_FOLDERS_TABLE,
    MEDIA_USAGES_TABLE,
)


def _tenant_fk() -> Mapped[UUID]:
    return mapped_column(
        GUID(length=16), ForeignKey(f'{TENANT_TABLE}.id', ondelete='cascade'), nullable=False, index=True
    )


def _organization_fk() -> Mapped[UUID]:
    return mapped_column(
        GUID(length=16), ForeignKey(f'{ORGANIZATION_TABLE}.id', ondelete='cascade'), nullable=False, index=True
    )


class MediaFolder(UUIDv7AuditBase):
    """Folder of an organization's media library (tree, depth ≤ 5)."""

    __tablename__ = MEDIA_FOLDERS_TABLE
    __table_args__ = (
        Index(
            'ux_taas_media_folders_name',
            'organization_id',
            text("coalesce(parent_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            text('lower(name)'),
            unique=True,
        ),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    organization_id: Mapped[UUID] = _organization_fk()
    parent_id: Mapped[UUID | None] = mapped_column(
        GUID(length=16), ForeignKey(f'{MEDIA_FOLDERS_TABLE}.id', ondelete='cascade'), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    color: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)


class MediaAsset(UUIDv7AuditBase, SoftDeleteColumns):
    """One media file (image, video, audio) with its processed variants. ``deleted_at`` = in the trash."""

    __tablename__ = MEDIA_ASSETS_TABLE
    __table_args__ = (
        Index('ix_taas_media_assets_org_kind', 'organization_id', 'kind'),
        Index('ix_taas_media_assets_org_folder', 'organization_id', 'folder_id'),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    organization_id: Mapped[UUID] = _organization_fk()
    folder_id: Mapped[UUID | None] = mapped_column(
        GUID(length=16), ForeignKey(f'{MEDIA_FOLDERS_TABLE}.id', ondelete='set null'), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    """``image`` · ``video`` · ``audio``."""
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    """Original file name (display / download name)."""
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    ext: Mapped[str] = mapped_column(String(16), nullable=False)
    mime: Mapped[str] = mapped_column(String(100), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    """Bytes of the original (variants not included)."""
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    alt: Mapped[str | None] = mapped_column(String(500), nullable=True)
    caption: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    focal_x: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    focal_y: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    key: Mapped[str] = mapped_column(String(1024), nullable=False)
    """Blob key of the original: ``media/<organization_id>/<asset_id>/original.<ext>``."""
    variants: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    """``{name: {key, width, height, format, size}}`` (``w320.webp``, ``w1280.avif``, …)."""
    variants_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    """SHA-256 of the stored original (duplicate detection)."""
    created_by: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    updated_by: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    deleted_by: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)


class MediaFavorite(UUIDv7AuditBase):
    """A user's favorite asset (quick tab "Favorites")."""

    __tablename__ = MEDIA_FAVORITES_TABLE
    __table_args__ = (UniqueConstraint('user_id', 'asset_id', name='uq_taas_media_favorites_user_asset'),)

    tenant_id: Mapped[UUID] = _tenant_fk()
    user_id: Mapped[UUID] = mapped_column(GUID(length=16), nullable=False, index=True)
    asset_id: Mapped[UUID] = mapped_column(
        GUID(length=16), ForeignKey(f'{MEDIA_ASSETS_TABLE}.id', ondelete='cascade'), nullable=False, index=True
    )


class MediaUsage(UUIDv7AuditBase):
    """Where an asset is used (e.g. app ``sites``, ref ``page`` + page id), maintained by the consumer app."""

    __tablename__ = MEDIA_USAGES_TABLE
    __table_args__ = (
        UniqueConstraint('asset_id', 'app', 'ref_type', 'ref_id', name='uq_taas_media_usages_ref'),
        Index('ix_taas_media_usages_ref', 'app', 'ref_type', 'ref_id'),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    asset_id: Mapped[UUID] = mapped_column(
        GUID(length=16), ForeignKey(f'{MEDIA_ASSETS_TABLE}.id', ondelete='cascade'), nullable=False, index=True
    )
    app: Mapped[str] = mapped_column(String(32), nullable=False)
    ref_type: Mapped[str] = mapped_column(String(32), nullable=False)
    ref_id: Mapped[UUID] = mapped_column(GUID(length=16), nullable=False)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    """Human label of the referrer, e.g. ``Acme site › About``."""
    used_at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True), nullable=False)
