"""Wire types of ``/api/v1/files`` (msgspec, snake_case JSON; fields equal to their default are omitted).
Members / roles reuse ``ews.access`` (``MemberOut``, ``MemberUpsert``, ``CandidateOut``, ``RoleOut``)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

import msgspec
from foundation.serialization import ApiRequest, ApiResponse

type OnConflict = Literal['version', 'keep_both', 'skip']
type NodeSort = Literal['name', 'updated', 'size', 'created']
type FileTypeFilter = Literal[
    'folder', 'file', 'document', 'image', 'video', 'audio', 'other'
]

# --- app ------------------------------------------------------------------------------------------


class FilesAccessOut(ApiResponse, kw_only=True):
    allowed: bool
    """Every signed-in member of the organization may open the app (at least *My files*)."""
    can_create_shared_drive: bool
    organization_drive_id: str | None = None
    """The organization's drive when the caller can read it."""
    personal_drive_id: str | None = None
    organization_slug: str
    max_upload_bytes: int
    delivery: Literal['proxy', 'presigned']


# --- drives ---------------------------------------------------------------------------------------


class FileDriveOut(ApiResponse, kw_only=True):
    id: str
    kind: Literal['organization', 'shared', 'personal']
    name: str
    description: str | None = None
    color: str | None = None
    organization_id: str | None = None
    owner_id: str | None = None
    default_member_role: str | None = None
    """Organization drive: role of the organization's direct members (``drive_editor`` · ``drive_viewer``)."""
    role: str | None = None
    """The caller's role: a grant on the drive, else the implicit one (owner, organization member)."""
    permissions: list[str] = msgspec.field(default_factory=list)
    """``files.*`` permissions of the caller on the drive (UI hints)."""
    file_count: int = 0
    size: int = 0
    """Bytes of the current versions of the live files."""
    created_at: datetime
    updated_at: datetime


class FileDriveCreate(ApiRequest, kw_only=True):
    name: str
    description: str | None = None
    color: str | None = None


class FileDriveUpdate(ApiRequest, kw_only=True):
    name: str | None = None
    description: str | None = None
    color: str | None | msgspec.UnsetType = msgspec.UNSET
    default_member_role: str | None = None


# --- nodes ----------------------------------------------------------------------------------------


class FileNodeRef(ApiResponse, kw_only=True):
    id: str
    name: str


class FileNodeOut(ApiResponse, kw_only=True):
    id: str
    drive_id: str
    drive_name: str | None = None
    """Set in cross-drive views (recent, starred, search)."""
    parent_id: str | None = None
    kind: Literal['folder', 'file']
    type: str
    """Quick tab: ``folder`` · ``document`` · ``image`` · ``video`` · ``audio`` · ``other``."""
    name: str
    ext: str | None = None
    mime: str | None = None
    size: int = 0
    version: int = 0
    current_version_id: str | None = None
    color: str | None = None
    starred: bool = False
    depth: int = 0
    created_by: str | None = None
    created_by_name: str | None = None
    updated_by: str | None = None
    updated_by_name: str | None = None
    created_at: datetime
    updated_at: datetime
    trashed_at: datetime | None = None
    trashed_by: str | None = None


class FileNodeDetailOut(FileNodeOut, kw_only=True):
    ancestors: list[FileNodeRef] = msgspec.field(default_factory=list)
    """Breadcrumb from the drive's top level to the parent."""
    permissions: list[str] = msgspec.field(default_factory=list)


class FileNodePage(ApiResponse, kw_only=True):
    items: list[FileNodeOut]
    total: int
    limit: int
    offset: int


class FileFolderCreate(ApiRequest, kw_only=True):
    name: str
    parent_id: str | None = None
    color: str | None = None


class FileNodeUpdate(ApiRequest, kw_only=True):
    name: str | None = None
    color: str | None | msgspec.UnsetType = msgspec.UNSET
    """``null`` removes the color."""


class FileNodeMove(ApiRequest, kw_only=True):
    parent_id: str | None = None
    """Destination folder of the same drive; ``null`` = the drive's top level."""


class FileNodeCopy(ApiRequest, kw_only=True):
    parent_id: str | None | msgspec.UnsetType = msgspec.UNSET
    """Destination folder of the same drive (default: the same folder); ``null`` = top level."""
    name: str | None = None


# --- uploads & versions ---------------------------------------------------------------------------


class FileUploadOut(ApiResponse, kw_only=True):
    result: Literal['created', 'versioned', 'skipped']
    node: FileNodeOut


class FileUploadRequest(ApiRequest, kw_only=True):
    """Direct upload: ask a ticket, ``PUT`` the bytes to ``url``, then ``POST /uploads/complete``."""

    name: str
    size: int
    mime: str | None = None
    parent_id: str | None = None
    on_conflict: OnConflict = 'version'
    node_id: str | None = None
    """Upload a new version of this file (*Upload new version*)."""
    relative_path: str | None = None
    """``a/b/report.pdf`` of a dropped folder: missing folders are created under ``parent_id``."""


class FileUploadTicketOut(ApiResponse, kw_only=True):
    skipped: bool = False
    """``on_conflict=skip`` and the name exists: nothing to upload (``node`` = the existing file)."""
    node: FileNodeOut | None = None
    token: str | None = None
    url: str | None = None
    method: str
    """``PUT`` (always present)."""
    headers: dict[str, str] = msgspec.field(default_factory=dict)
    expires_at: datetime | None = None
    max_bytes: int = 0


class FileUploadComplete(ApiRequest, kw_only=True):
    token: str
    comment: str | None = None


class FileVersionOut(ApiResponse, kw_only=True):
    id: str
    number: int
    size: int
    mime: str
    checksum: str | None = None
    comment: str | None = None
    scan_status: str
    restored_from: int | None = None
    uploaded_by: str | None = None
    uploaded_by_name: str | None = None
    current: bool = False
    created_at: datetime


class FileVersionUpdate(ApiRequest, kw_only=True):
    comment: str | None = None


class FileDownloadOut(ApiResponse, kw_only=True):
    url: str
    """Signed URL, valid 1–5 min (``FILES_URL_TTL_SECONDS``)."""
    filename: str
    mime: str
    size: int
    inline: bool
    """``false`` when a preview was asked for a risky type: the file is downloaded (File-0206)."""
    expires_at: datetime


# --- activity & views -----------------------------------------------------------------------------


class FileActivityOut(ApiResponse, kw_only=True):
    id: str
    drive_id: str
    node_id: str | None = None
    actor_id: str | None = None
    actor_name: str | None = None
    action: str
    detail: dict[str, Any] = msgspec.field(default_factory=dict)
    created_at: datetime


class FilesHomeOut(ApiResponse, kw_only=True):
    drives: list[FileDriveOut]
    recent: list[FileNodeOut]


class FileCountOut(ApiResponse, kw_only=True):
    count: int
