"""Wire types of the project / item files routes (File Manager source drive + web links, Ppm-0840…0843)."""

from __future__ import annotations

from datetime import datetime

from foundation.serialization import ApiRequest, ApiResponse


class PpmFilesOut(ApiResponse, kw_only=True):
    drive_id: str
    """The project's source drive in the File Manager (``/api/v1/files/drives/{drive_id}``)."""
    folder_id: str | None = None
    """Folder of the item's attachments (``Tasks/<code>``); ``None`` = the project files (drive root)."""


class PpmLinkOut(ApiResponse, kw_only=True):
    id: str
    url: str
    title: str
    added_by: str | None = None
    created_at: datetime


class PpmLinkCreate(ApiRequest, kw_only=True):
    url: str
    title: str | None = None
