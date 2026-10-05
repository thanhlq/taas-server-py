"""Blob storage value types (contract §3, `taas-specs/blob-storage-service`)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Literal

type BlobProvider = Literal['s3', 'gcp', 'azure', 'memory']
"""Provider of a blob adapter (`BlobAdapterT.provider`)."""

type BlobBody = bytes | str
"""Body accepted by `put`: strings are UTF-8 encoded."""

type BlobPresignMethod = Literal['GET', 'PUT']

DEFAULT_CONTENT_TYPE: Final[str] = 'application/octet-stream'
DEFAULT_LIST_LIMIT: Final[int] = 1000
MAX_LIST_LIMIT: Final[int] = 1000
MAX_PRESIGN_EXPIRES: Final[int] = 604800  # 7 days (SigV4 / GCS V4 maximum)
DEFAULT_PRESIGN_EXPIRES: Final[int] = 900


@dataclass(frozen=True, slots=True, kw_only=True)
class BlobInfo:
    """Description of a stored object."""

    bucket: str
    key: str
    size: int
    """Size in bytes."""
    content_type: str | None = None
    """`None` if unknown (e.g. S3 list items)."""
    etag: str | None = None
    """Entity tag, quotes stripped."""
    last_modified: datetime | None = None
    """UTC timestamp."""
    metadata: dict[str, str] = field(default_factory=dict[str, str])
    """User metadata, keys lower-case."""


@dataclass(frozen=True, slots=True, kw_only=True)
class BlobObject:
    """An object with its content."""

    info: BlobInfo
    body: bytes


@dataclass(frozen=True, slots=True, kw_only=True)
class BlobPutOptions:
    content_type: str = DEFAULT_CONTENT_TYPE
    metadata: dict[str, str] = field(default_factory=dict[str, str])
    cache_control: str | None = None
    content_disposition: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class BlobListOptions:
    prefix: str | None = None
    cursor: str | None = None
    """Opaque cursor from the previous page (`BlobPage.next_cursor`)."""
    limit: int = DEFAULT_LIST_LIMIT
    """1..1000."""


@dataclass(frozen=True, slots=True, kw_only=True)
class BlobPage:
    items: list[BlobInfo]
    """Objects in key order."""
    next_cursor: str | None = None
    """`None` at the end."""


@dataclass(frozen=True, slots=True, kw_only=True)
class BlobPresignOptions:
    method: BlobPresignMethod = 'GET'
    expires_in: int | None = None
    """Seconds (1..604800); `None` = `BLOB_PRESIGN_EXPIRES`."""
    content_type: str | None = None
    """PUT only: the content type the uploader must send."""
    download_name: str | None = None
    """GET only: `Content-Disposition: attachment; filename="…"`."""


@dataclass(frozen=True, slots=True, kw_only=True)
class TenantBucketRecord:
    """Result of `TenantBucketRegistryT.get`: the tenant code and its stored bucket (`None` = not provisioned)."""

    tenant_code: str
    bucket: str | None = None
