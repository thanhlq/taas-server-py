"""Key / bucket / option validation shared by every adapter (contract §2, §3, §5)."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Final

from .blob_errors import BlobValidationError
from .blob_types import (
    MAX_LIST_LIMIT,
    MAX_PRESIGN_EXPIRES,
    BlobBody,
    BlobListOptions,
    BlobPresignOptions,
)

BUCKET_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(
    r'^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$'
)
"""Valid for S3, R2, GCS and Azure containers (Azure also rejects `--`, checked separately)."""

METADATA_KEY_PATTERN: Final[re.Pattern[str]] = re.compile(r'^[a-z][a-z0-9_]{0,62}$')
"""User metadata keys after lower-casing: letters, digits and `_` (Azure: C# identifiers)."""

MAX_KEY_BYTES: Final[int] = 1024


def _has_control_chars(value: str) -> bool:
    return any(unicodedata.category(ch) == 'Cc' for ch in value)


def _is_int_in_range(value: object, maximum: int) -> bool:
    """`1 <= value <= maximum` for a real int (bool excluded)."""
    return (
        isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= maximum
    )


def validate_bucket_name(bucket: str) -> str:
    """Return `bucket` when it matches `^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$` without `--`, else `BlobValidationError`."""
    if (
        not isinstance(bucket, str)  # pyright: ignore[reportUnnecessaryIsInstance]
        or not BUCKET_NAME_PATTERN.fullmatch(bucket)
        or '--' in bucket
    ):
        raise BlobValidationError(f'Invalid bucket name: {bucket!r}')
    return bucket


def validate_key(key: str) -> str:
    """Return `key` when valid, else raise `BlobValidationError`.

    1..1024 UTF-8 bytes, relative (`/` separated), no leading `/`, no `.` / `..` segment,
    no empty segment, no control characters.
    """
    if not isinstance(key, str) or not key:  # pyright: ignore[reportUnnecessaryIsInstance]
        raise BlobValidationError('Invalid blob key: empty')
    if len(key.encode('utf-8')) > MAX_KEY_BYTES:
        raise BlobValidationError(
            f'Invalid blob key: longer than {MAX_KEY_BYTES} UTF-8 bytes'
        )
    if _has_control_chars(key):
        raise BlobValidationError(f'Invalid blob key {key!r}: control characters')
    if key.startswith('/'):
        raise BlobValidationError(f'Invalid blob key {key!r}: leading "/"')
    for segment in key.split('/'):
        if segment == '':
            raise BlobValidationError(f'Invalid blob key {key!r}: empty segment')
        if segment in ('.', '..'):
            raise BlobValidationError(f'Invalid blob key {key!r}: "." or ".." segment')
    return key


def validate_keys(keys: Iterable[str]) -> list[str]:
    """Validate every key; returns them de-duplicated, in first-seen order."""
    return list(dict.fromkeys(validate_key(key) for key in keys))


def validate_list_options(options: BlobListOptions | None) -> BlobListOptions:
    """Return valid list options (`limit` in 1..1000; the prefix is free text)."""
    options = options or BlobListOptions()
    if not _is_int_in_range(options.limit, MAX_LIST_LIMIT):
        raise BlobValidationError(
            f'Invalid list limit {options.limit!r}: expected 1..{MAX_LIST_LIMIT}'
        )
    return options


def resolve_presign_expires(options: BlobPresignOptions, default_expires: int) -> int:
    """Return `options.expires_in` (or `default_expires`), checked to be in 1..604800 seconds."""
    expires = options.expires_in if options.expires_in is not None else default_expires
    if not _is_int_in_range(expires, MAX_PRESIGN_EXPIRES):
        raise BlobValidationError(
            f'Invalid presign expiry {expires!r}: expected 1..{MAX_PRESIGN_EXPIRES} seconds'
        )
    if options.method not in ('GET', 'PUT'):
        raise BlobValidationError(
            f'Invalid presign method {options.method!r}: expected GET or PUT'
        )
    return expires


def body_to_bytes(body: BlobBody) -> bytes:
    """`bytes` (or bytes-like) as is, `str` UTF-8 encoded."""
    if isinstance(body, str):
        return body.encode('utf-8')
    if isinstance(body, (bytes, bytearray, memoryview)):  # pyright: ignore[reportUnnecessaryIsInstance]
        return bytes(body)
    raise BlobValidationError(f'Invalid blob body type: {type(body).__name__}')


def normalize_metadata(metadata: Mapping[str, str] | None) -> dict[str, str]:
    """Lenient (reads): keys lower-cased, values as strings, `None` values dropped."""
    return {
        str(name).lower(): str(value)
        for name, value in (metadata or {}).items()
        if value is not None  # pyright: ignore[reportUnnecessaryComparison]
    }


def validate_metadata(metadata: Mapping[str, str] | None) -> dict[str, str]:
    """Writes: `normalize_metadata`, then every key must match `^[a-z][a-z0-9_]{0,62}$` (portable to Azure)."""
    result = normalize_metadata(metadata)
    for name in result:
        if not METADATA_KEY_PATTERN.fullmatch(name):
            raise BlobValidationError(
                f"Invalid metadata key {name!r}: letters, digits and '_' only"
            )
    return result


_DISPOSITION_UNSAFE: Final[re.Pattern[str]] = re.compile(r'["\\\x00-\x1f\x7f-\x9f]')


def attachment_disposition(download_name: str) -> str:
    """`attachment; filename="…"` (`"`, `\\` and control characters replaced by `_`)."""
    return f'attachment; filename="{_DISPOSITION_UNSAFE.sub("_", download_name)}"'


def strip_etag(etag: str | None) -> str | None:
    """`"abc"` / `W/"abc"` → `abc`."""
    if not etag:
        return None
    value = etag.strip()
    value = value.removeprefix('W/')
    return value.strip('"') or None
