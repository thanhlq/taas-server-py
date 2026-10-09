"""File Manager (app ``files``): drives, the folder / file tree, immutable file versions, activity, stars, and the
derived data of the processing pipeline (previews, the local search index).

- Drives: one **organization** drive per organization, **shared** drives (explicit members), one **personal**
  drive ("My files") per user and tenant (``organization_id`` NULL). RBAC domain ``drive:<id>``.
- Nodes: folders and files of a drive as a materialized-path tree (``path`` = ``/<root id>/…/<id>/``, ≤ 20
  levels). ``trashed_at`` = in the trash (with its subtree, ``trash_root_id`` = the node the user deleted);
  ``deleted_at`` = purged (storage objects removed, row kept for the activity log).
- Versions: append-only; storage key ``documents/drives/{drive_id}/{node_id}/{version_id}`` (kind ``document``).
  ``pipeline_status`` = the processing queue (checksum, metadata, previews, text index — ``ews.files._pipeline``).
- Previews: generated variants (``thumb``, ``preview``) in ``derived/files/{node_id}/{version_id}/{variant}.webp``.
- Contents: extracted text of the current version + a generated ``tsvector`` (local full-text index, GIN). Names are
  searched through a trigram index (``ix_taas_file_nodes_name_trgm``, migration only: needs ``pg_trgm``).

Spec: taas-specs/files/file-manager-app-spec.md §9 (data model), files-architecture.md.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from advanced_alchemy.base import UUIDv7AuditBase, UUIDv7Base
from advanced_alchemy.types import GUID, DateTimeUTC
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from db.models.base import JSONB, SoftDeleteColumns
from db.models.core.constants import ORGANIZATION_TABLE, TENANT_TABLE

from .constants import (
    FILE_ACTIVITY_TABLE,
    FILE_CONTENTS_TABLE,
    FILE_DRIVES_TABLE,
    FILE_NODES_TABLE,
    FILE_PREVIEWS_TABLE,
    FILE_STARS_TABLE,
    FILE_VERSIONS_TABLE,
)

_ZERO_UUID = "'00000000-0000-0000-0000-000000000000'::uuid"


def _tenant_fk() -> Mapped[UUID]:
    return mapped_column(
        GUID(length=16),
        ForeignKey(f'{TENANT_TABLE}.id', ondelete='cascade'),
        nullable=False,
        index=True,
    )


def _node_fk() -> Mapped[UUID]:
    return mapped_column(
        GUID(length=16),
        ForeignKey(f'{FILE_NODES_TABLE}.id', ondelete='cascade'),
        nullable=False,
        index=True,
    )


class FileDrive(UUIDv7AuditBase, SoftDeleteColumns):
    """A drive (RBAC domain ``drive:<id>``): ``organization`` · ``shared`` · ``personal``."""

    __tablename__ = FILE_DRIVES_TABLE
    __table_args__ = (
        CheckConstraint(
            "kind in ('organization', 'shared', 'personal')",
            name='ck_taas_file_drives_kind',
        ),
        CheckConstraint(
            "(kind = 'personal') = (organization_id is null)",
            name='ck_taas_file_drives_owner',
        ),
        Index(
            'ux_taas_file_drives_organization',
            'organization_id',
            unique=True,
            postgresql_where=text("kind = 'organization' AND deleted_at IS NULL"),
        ),
        Index(
            'ux_taas_file_drives_personal',
            'tenant_id',
            'owner_id',
            unique=True,
            postgresql_where=text("kind = 'personal' AND deleted_at IS NULL"),
        ),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    organization_id: Mapped[UUID | None] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{ORGANIZATION_TABLE}.id', ondelete='cascade'),
        nullable=True,
        index=True,
    )
    """Owning organization (organization and shared drives); NULL for personal drives."""
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    owner_id: Mapped[UUID | None] = mapped_column(
        GUID(length=16), nullable=True, index=True
    )
    """User of a personal drive (implicit ``drive_manager``)."""
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    color: Mapped[str | None] = mapped_column(String(32), nullable=True)
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    """``{default_member_role, sensitivity, url_epoch}``: role of the organization's direct members (organization
    drive), ``standard`` · ``confidential`` (lifetime / caching of signed URLs), revocation counter of signed URLs."""
    created_by: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)


class FileNode(UUIDv7AuditBase, SoftDeleteColumns):
    """A folder or a file of a drive. ``deleted_at`` = purged (blobs removed)."""

    __tablename__ = FILE_NODES_TABLE
    __table_args__ = (
        CheckConstraint("kind in ('folder', 'file')", name='ck_taas_file_nodes_kind'),
        Index(
            'ux_taas_file_nodes_name',
            'drive_id',
            text(f'coalesce(parent_id, {_ZERO_UUID})'),
            text('lower(name)'),
            unique=True,
            postgresql_where=text('trashed_at IS NULL AND deleted_at IS NULL'),
        ),
        Index('ix_taas_file_nodes_drive_parent', 'drive_id', 'parent_id'),
        Index(
            'ix_taas_file_nodes_path',
            'path',
            postgresql_ops={'path': 'varchar_pattern_ops'},
        ),
        Index('ix_taas_file_nodes_drive_updated', 'drive_id', 'updated_at'),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    drive_id: Mapped[UUID] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{FILE_DRIVES_TABLE}.id', ondelete='cascade'),
        nullable=False,
        index=True,
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{FILE_NODES_TABLE}.id', ondelete='cascade'),
        nullable=True,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    """``folder`` · ``file``."""
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    """Materialized path ``/<root id>/…/<id>/`` (``ews.shared`` tree helpers)."""
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    color: Mapped[str | None] = mapped_column(String(32), nullable=True)
    current_version_id: Mapped[UUID | None] = mapped_column(
        GUID(length=16), nullable=True
    )
    """Current ``taas_file_versions`` row of a file (no FK: versions reference their node)."""
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    """Number of the current version (0 for folders)."""
    size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    mime: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ext: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    updated_by: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    trashed_at: Mapped[datetime | None] = mapped_column(
        DateTimeUTC(timezone=True), nullable=True
    )
    trashed_by: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    trash_root_id: Mapped[UUID | None] = mapped_column(
        GUID(length=16), nullable=True, index=True
    )
    """The node whose deletion put this one in the trash (= its own id for the item the user deleted)."""


def _version_fk() -> Mapped[UUID]:
    return mapped_column(
        GUID(length=16),
        ForeignKey(f'{FILE_VERSIONS_TABLE}.id', ondelete='cascade'),
        nullable=False,
    )


class FileVersion(UUIDv7Base):
    """An immutable version of a file (File-0301) and the state of its processing (File-0600)."""

    __tablename__ = FILE_VERSIONS_TABLE
    __table_args__ = (
        UniqueConstraint('node_id', 'number', name='uq_taas_file_versions_number'),
        CheckConstraint(
            "scan_status in ('pending', 'clean', 'infected', 'skipped', 'failed')",
            name='ck_taas_file_versions_scan_status',
        ),
        CheckConstraint(
            "pipeline_status in ('pending', 'running', 'done', 'failed')",
            name='ck_taas_file_versions_pipeline_status',
        ),
        CheckConstraint(
            "preview_status in ('pending', 'ready', 'none', 'failed')",
            name='ck_taas_file_versions_preview_status',
        ),
        CheckConstraint(
            "index_status in ('pending', 'ready', 'none', 'failed')",
            name='ck_taas_file_versions_index_status',
        ),
        Index(
            'ix_taas_file_versions_pipeline',
            'created_at',
            postgresql_where=text("pipeline_status in ('pending', 'running')"),
        ),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    node_id: Mapped[UUID] = _node_fk()
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    key: Mapped[str] = mapped_column(String(1024), nullable=False)
    """Storage key relative to the tenant root: ``documents/drives/{drive}/{node}/{version id}``."""
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime: Mapped[str] = mapped_column(String(255), nullable=False)
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    """SHA-256 (API uploads); NULL for direct (presigned) uploads."""
    comment: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    scan_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default='skipped'
    )
    """Malware scan (P2): ``skipped`` until the scanner exists."""
    restored_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """Number of the version this one restores (File-0301 restore)."""
    uploaded_by: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTimeUTC(timezone=True), nullable=False
    )
    pipeline_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default='pending', server_default='pending'
    )
    """Processing queue: ``pending`` → ``running`` (claimed, ``pipeline_at``) → ``done`` · ``failed`` (3 attempts)."""
    pipeline_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default='0'
    )
    pipeline_at: Mapped[datetime | None] = mapped_column(
        DateTimeUTC(timezone=True), nullable=True
    )
    """When the job was claimed (``running``) or finished."""
    pipeline_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    preview_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default='pending', server_default='pending'
    )
    """``pending`` · ``ready`` (rows in ``taas_file_previews``) · ``none`` (no preview for this type) · ``failed``."""
    index_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default='pending', server_default='pending'
    )
    """``pending`` · ``ready`` (row in ``taas_file_contents``) · ``none`` (no text / not current) · ``failed``."""
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    """Extracted metadata: ``sniffed`` (type from the content), ``width`` / ``height``, ``pages``, ``title``,
    ``author``, ``taken_at``, ``words``."""


class FilePreview(UUIDv7Base):
    """A generated variant of a version (File-0302): ``thumb`` (grid, ≤ 480 px) · ``preview`` (viewer, ≤ 1920 px)."""

    __tablename__ = FILE_PREVIEWS_TABLE
    __table_args__ = (
        UniqueConstraint('version_id', 'variant', name='uq_taas_file_previews_variant'),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    node_id: Mapped[UUID] = _node_fk()
    version_id: Mapped[UUID] = _version_fk()
    variant: Mapped[str] = mapped_column(String(16), nullable=False)
    key: Mapped[str] = mapped_column(String(1024), nullable=False)
    """Storage key relative to the tenant root: ``derived/files/{node}/{version}/{variant}.webp``."""
    mime: Mapped[str] = mapped_column(String(64), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    placeholder: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    """Tiny blurred image as a ``data:`` URI (``thumb`` only), shown while the thumbnail loads."""
    created_at: Mapped[datetime] = mapped_column(
        DateTimeUTC(timezone=True), nullable=False
    )


class FileContent(UUIDv7Base):
    """Extracted text of a file's **current** version — the local full-text index (File-0400)."""

    __tablename__ = FILE_CONTENTS_TABLE
    __table_args__ = (
        UniqueConstraint('version_id', name='uq_taas_file_contents_version'),
        Index('ix_taas_file_contents_tsv', 'tsv', postgresql_using='gin'),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    node_id: Mapped[UUID] = _node_fk()
    version_id: Mapped[UUID] = _version_fk()
    text: Mapped[str] = mapped_column(Text, nullable=False)
    """Plain text, capped at ``FILES_INDEX_MAX_CHARS`` (``truncated``)."""
    chars: Mapped[int] = mapped_column(Integer, nullable=False)
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tsv: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple'::regconfig, text)", persisted=True),
        nullable=True,
    )
    """Generated by the database (``simple`` configuration: no stemming, every language)."""
    created_at: Mapped[datetime] = mapped_column(
        DateTimeUTC(timezone=True), nullable=False
    )


class FileActivity(UUIDv7Base):
    """Activity / audit row of a drive or node (File-0307); kept when the node is purged."""

    __tablename__ = FILE_ACTIVITY_TABLE
    __table_args__ = (
        Index('ix_taas_file_activity_drive', 'drive_id', 'created_at'),
        Index('ix_taas_file_activity_node', 'node_id', 'created_at'),
        Index('ix_taas_file_activity_actor', 'tenant_id', 'actor_id', 'created_at'),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    drive_id: Mapped[UUID] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{FILE_DRIVES_TABLE}.id', ondelete='cascade'),
        nullable=False,
    )
    node_id: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    """No FK: the row outlives a purged node."""
    actor_id: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    """NULL = the system (trash retention)."""
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTimeUTC(timezone=True), nullable=False
    )


class FileStar(UUIDv7AuditBase):
    """A user's starred node (view *Starred*)."""

    __tablename__ = FILE_STARS_TABLE
    __table_args__ = (
        UniqueConstraint('user_id', 'node_id', name='uq_taas_file_stars_user_node'),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    user_id: Mapped[UUID] = mapped_column(GUID(length=16), nullable=False, index=True)
    node_id: Mapped[UUID] = _node_fk()
