"""Blob storage errors (contract §5): `BlobError` base with a stable `code`."""

from __future__ import annotations

from typing import ClassVar


class BlobError(Exception):
    """Base error of the blob storage service."""

    code: ClassVar[str] = 'blob_error'

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class BlobValidationError(BlobError, ValueError):
    """Invalid key, bucket name, option or setting."""

    code: ClassVar[str] = 'invalid_blob_request'


class BlobNotFoundError(BlobError):
    """A required object (e.g. copy source) or bucket is missing."""

    code: ClassVar[str] = 'blob_not_found'


class BlobConflictError(BlobError):
    """Conflicting state (e.g. deleting a non-empty bucket, bucket name owned by someone else)."""

    code: ClassVar[str] = 'blob_conflict'


class BlobTenantNotFoundError(BlobError):
    """The tenant does not exist in `taas_tenants`."""

    code: ClassVar[str] = 'blob_tenant_not_found'


class BlobProviderError(BlobError):
    """Wraps an SDK / provider error; the message names the provider and the operation."""

    code: ClassVar[str] = 'blob_provider_error'

    def __init__(
        self, provider: str, operation: str, cause: BaseException | str
    ) -> None:
        super().__init__(f'{provider} {operation} failed: {cause}')
        self.provider = provider
        self.operation = operation
