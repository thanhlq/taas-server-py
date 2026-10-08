"""Knowledge Center (app ``knowledge``): spaces with a visibility, a page tree per space, page revisions (the
draft + one immutable version per publish) and private attachments (storage kind ``knowledge/``).

Access: RBAC domain ``kb-space:<id>`` → the space organization's chain → ``tenant:<id>``; the visibility grants
``kb_space_viewer`` implicitly (``ews.knowledge._access``). Spec: taas-specs/knowledge/.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from advanced_alchemy.base import UUIDv7AuditBase
from advanced_alchemy.types import GUID, DateTimeUTC
from sqlalchemy import (
    BigInteger,
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

from db.models.base import JSONB, SoftDeleteColumns
from db.models.core.constants import ORGANIZATION_TABLE, TENANT_TABLE

from .constants import (
    KB_ATTACHMENTS_TABLE,
    KB_PAGE_REVISIONS_TABLE,
    KB_PAGES_TABLE,
    KB_SPACES_TABLE,
)


def _tenant_fk() -> Mapped[UUID]:
    return mapped_column(
        GUID(length=16),
        ForeignKey(f'{TENANT_TABLE}.id', ondelete='cascade'),
        nullable=False,
        index=True,
    )


def _space_fk() -> Mapped[UUID]:
    return mapped_column(
        GUID(length=16),
        ForeignKey(f'{KB_SPACES_TABLE}.id', ondelete='cascade'),
        nullable=False,
        index=True,
    )


def _page_fk() -> Mapped[UUID]:
    return mapped_column(
        GUID(length=16),
        ForeignKey(f'{KB_PAGES_TABLE}.id', ondelete='cascade'),
        nullable=False,
        index=True,
    )


class KbSpace(UUIDv7AuditBase, SoftDeleteColumns):
    """A knowledge space (RBAC domain ``kb-space:<id>``), owned by the organization that created it (Kb-0100)."""

    __tablename__ = KB_SPACES_TABLE
    __table_args__ = (
        Index(
            'ux_taas_kb_spaces_tenant_slug',
            'tenant_id',
            'slug',
            unique=True,
            postgresql_where=text('deleted_at IS NULL'),
        ),
        # naming convention ``ck_<table>_<name>`` → ``ck_taas_kb_spaces_visibility``
        CheckConstraint(
            "visibility IN ('tenant', 'organization', 'restricted')", name='visibility'
        ),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    organization_id: Mapped[UUID] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{ORGANIZATION_TABLE}.id', ondelete='cascade'),
        nullable=False,
        index=True,
    )
    """Organization that owns the space: its admins manage it; the audience of ``organization`` visibility."""
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(60), nullable=False)
    """Unique per tenant among live spaces."""
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(40), nullable=True)
    """Lucide icon name."""
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    """``#rrggbb``."""
    visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, default='organization'
    )
    """``tenant`` · ``organization`` · ``restricted`` (``public`` help center: P2)."""
    include_sub_orgs: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    """``organization`` visibility: members of the sub-organizations read too."""
    created_by: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    updated_by: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)


class KbPage(UUIDv7AuditBase, SoftDeleteColumns):
    """A page of a space's tree (materialized ``path`` of ids, ≤ 10 levels); content lives in revisions."""

    __tablename__ = KB_PAGES_TABLE
    __table_args__ = (
        Index('ix_taas_kb_pages_space_parent', 'space_id', 'parent_id', 'position'),
        Index(
            'ix_taas_kb_pages_path', 'path', postgresql_ops={'path': 'text_pattern_ops'}
        ),
        Index('ix_taas_kb_pages_owner', 'tenant_id', 'owner_id'),
        Index(
            'ux_taas_kb_pages_space_slug',
            'space_id',
            'slug',
            unique=True,
            postgresql_where=text('deleted_at IS NULL'),
        ),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    space_id: Mapped[UUID] = _space_fk()
    parent_id: Mapped[UUID | None] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{KB_PAGES_TABLE}.id', ondelete='cascade'),
        nullable=True,
    )
    path: Mapped[str] = mapped_column(String(512), nullable=False)
    """Ids of the ancestors and the page, ``/<root>/<child>/`` (``ews.shared`` tree helpers)."""
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    """0 = top level."""
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    """Title of the draft (editors)."""
    published_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    """Title of the published version (readers); ``None`` = never published."""
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    owner_id: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    """Accountable for the content (default: the creator) — Kb-0303."""
    review_interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """``None`` = no periodic review."""
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTimeUTC(timezone=True), nullable=True
    )
    verified_by: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    verified_until: Mapped[datetime | None] = mapped_column(
        DateTimeUTC(timezone=True), nullable=True
    )
    draft_revision_id: Mapped[UUID | None] = mapped_column(
        GUID(length=16), nullable=True
    )
    published_revision_id: Mapped[UUID | None] = mapped_column(
        GUID(length=16), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTimeUTC(timezone=True), nullable=True
    )
    published_by: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    search_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Plain text of the published version (simple search, Kb-0104)."""
    locked_by: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTimeUTC(timezone=True), nullable=True
    )
    """Soft lock while editing (Kb-0302); expired = free."""
    created_by: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    updated_by: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)


class KbPageRevision(UUIDv7AuditBase):
    """A page document: the working draft (``version`` null, autosaved in place) or a published version
    (``version`` 1, 2, … — immutable)."""

    __tablename__ = KB_PAGE_REVISIONS_TABLE
    __table_args__ = (Index('ix_taas_kb_page_revisions_page', 'page_id', 'created_at'),)

    tenant_id: Mapped[UUID] = _tenant_fk()
    space_id: Mapped[UUID] = _space_fk()
    page_id: Mapped[UUID] = _page_fk()
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    doc: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    """Site document ``{schemaVersion, sections}`` (shared with the Site Builder)."""
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default='editor')
    """``editor`` · ``markdown`` · ``template`` · ``restore`` · ``import``."""
    version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """Published version number; ``None`` = draft."""
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    author_id: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    """Last editor of the draft / author of the version."""
    published_at: Mapped[datetime | None] = mapped_column(
        DateTimeUTC(timezone=True), nullable=True
    )
    published_by: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)


class KbAttachment(UUIDv7AuditBase, SoftDeleteColumns):
    """A private file of a page (storage kind ``knowledge/``), delivered through short signed URLs (Kb-0305)."""

    __tablename__ = KB_ATTACHMENTS_TABLE

    tenant_id: Mapped[UUID] = _tenant_fk()
    space_id: Mapped[UUID] = _space_fk()
    page_id: Mapped[UUID] = _page_fk()
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime: Mapped[str] = mapped_column(String(128), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    key: Mapped[str] = mapped_column(String(1024), nullable=False)
    """Relative to the tenant root: ``knowledge/<space_id>/<attachment_id>/<version>/original[.ext]``."""
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    """SHA-256 (hex)."""
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
