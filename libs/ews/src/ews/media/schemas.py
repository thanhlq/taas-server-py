"""Wire types of ``/api/v1/media`` (msgspec, snake_case JSON)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

import msgspec
from foundation.serialization import ApiRequest, ApiResponse

type MediaTab = Literal['all', 'recent', 'favorites', 'images', 'videos', 'audio', 'trash']
type MediaSort = Literal['name', 'size', 'created', 'updated']


class MediaAssetOut(ApiResponse, kw_only=True):
    id: str
    kind: str
    title: str
    filename: str
    ext: str
    mime: str
    size: int
    width: int | None = None
    height: int | None = None
    alt: str | None = None
    caption: str | None = None
    focal_x: float = 0.5
    focal_y: float = 0.5
    folder_id: str | None = None
    favorite: bool = False
    url: str
    """Original file (signed, expires)."""
    thumb_url: str | None = None
    """Small preview (320 px WebP; the original for SVG; ``None`` for video / audio)."""
    preview_url: str | None = None
    """Large preview (1280 px WebP or the original)."""
    variants: list[str] = msgspec.field(default_factory=list)
    usage_count: int = 0
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class MediaAssetPage(ApiResponse, kw_only=True):
    items: list[MediaAssetOut]
    total: int
    limit: int
    offset: int


class MediaAssetUpdate(ApiRequest, kw_only=True):
    title: str | None = None
    alt: str | None = None
    caption: str | None = None
    focal_x: float | None = None
    focal_y: float | None = None
    folder_id: str | None | msgspec.UnsetType = msgspec.UNSET
    """``null`` moves the asset to the library root."""


class MediaBulkRequest(ApiRequest, kw_only=True):
    action: Literal['move', 'trash', 'restore', 'delete']
    ids: list[str]
    folder_id: str | None = None


class MediaCountOut(ApiResponse, kw_only=True):
    count: int


class MediaFolderOut(ApiResponse, kw_only=True):
    id: str
    name: str
    parent_id: str | None = None
    color: str | None = None
    asset_count: int = 0
    created_at: datetime


class MediaFolderCreate(ApiRequest, kw_only=True):
    name: str
    parent_id: str | None = None
    color: str | None = None


class MediaFolderUpdate(ApiRequest, kw_only=True):
    name: str | None = None
    color: str | None = None
    parent_id: str | None | msgspec.UnsetType = msgspec.UNSET


class MediaUsageOut(ApiResponse, kw_only=True):
    app: str
    ref_type: str
    ref_id: str
    label: str | None = None
    used_at: datetime


class MediaKindUsage(ApiResponse, kw_only=True):
    kind: str
    count: int
    size: int


class MediaStorageOut(ApiResponse, kw_only=True):
    used: int
    """Bytes stored by the tenant (originals + variants, trash included)."""
    quota: int
    """0 = unlimited."""
    count: int
    trash_count: int
    by_kind: list[MediaKindUsage]
    max_upload: dict[str, int]
    """Size limit per kind (bytes)."""
    permissions: list[str] = msgspec.field(default_factory=list)
    """``media.*`` permissions of the caller in the organization, e.g. ``media.asset:delete``."""


class MediaResolveRequest(ApiRequest, kw_only=True):
    ids: list[str]


class MediaSource(ApiResponse, kw_only=True):
    url: str
    width: int
    format: str


class MediaResolved(ApiResponse, kw_only=True):
    id: str
    kind: str
    mime: str
    title: str
    url: str
    width: int | None = None
    height: int | None = None
    alt: str | None = None
    focal_x: float = 0.5
    focal_y: float = 0.5
    sources: list[MediaSource] = msgspec.field(default_factory=list)
    """Responsive variants (WebP / AVIF) for ``srcset``."""


class MediaResolveOut(ApiResponse, kw_only=True):
    items: list[MediaResolved]


class MediaDownloadOut(ApiResponse, kw_only=True):
    url: str
    filename: str
