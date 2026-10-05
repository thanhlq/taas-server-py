"""In-memory `BlobAdapterT` (tests, local dev). Not shared between processes."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from urllib.parse import quote, urlencode

from foundation.blob import (
    DEFAULT_PRESIGN_EXPIRES,
    BlobAdapterT,
    BlobBody,
    BlobConflictError,
    BlobInfo,
    BlobListOptions,
    BlobNotFoundError,
    BlobObject,
    BlobPage,
    BlobPresignOptions,
    BlobProvider,
    BlobPutOptions,
    attachment_disposition,
    body_to_bytes,
    validate_metadata,
    resolve_presign_expires,
    validate_bucket_name,
    validate_key,
    validate_keys,
    validate_list_options,
)


@dataclass(slots=True)
class _Stored:
    info: BlobInfo
    body: bytes
    cache_control: str | None = None
    content_disposition: str | None = None


@dataclass(slots=True)
class _Bucket:
    objects: dict[str, _Stored] = field(default_factory=dict[str, _Stored])


class MemoryBlobAdapter(BlobAdapterT):
    """Dict-backed adapter with the same validation and semantics as the cloud adapters.

    Presigned URLs are `memory://<bucket>/<key>?method=…&expires_in=…` (not fetchable).
    Missing bucket: `put` / `get` / `list` / `copy` raise `BlobNotFoundError`, `head` / `exists` return
    `None` / `False`, `delete` / `delete_many` are no-ops (as every adapter).
    """

    def __init__(self, *, presign_expires: int | None = None) -> None:
        self._buckets: dict[str, _Bucket] = {}
        self._presign_expires = presign_expires or DEFAULT_PRESIGN_EXPIRES

    @property
    def provider(self) -> BlobProvider:
        return 'memory'

    def _bucket(self, bucket: str) -> _Bucket:
        found = self._buckets.get(validate_bucket_name(bucket))
        if found is None:
            raise BlobNotFoundError(f'Bucket not found: {bucket}')
        return found

    async def ensure_bucket(self, bucket: str) -> None:
        self._buckets.setdefault(validate_bucket_name(bucket), _Bucket())

    async def bucket_exists(self, bucket: str) -> bool:
        return validate_bucket_name(bucket) in self._buckets

    async def delete_bucket(self, bucket: str) -> None:
        found = self._buckets.get(validate_bucket_name(bucket))
        if found is None:
            return
        if found.objects:
            raise BlobConflictError(f'Bucket not empty: {bucket}')
        del self._buckets[bucket]

    async def put(
        self,
        bucket: str,
        key: str,
        body: BlobBody,
        options: BlobPutOptions | None = None,
    ) -> BlobInfo:
        options = options or BlobPutOptions()
        validate_key(key)
        target = self._bucket(bucket)
        data = body_to_bytes(body)
        info = BlobInfo(
            bucket=bucket,
            key=key,
            size=len(data),
            content_type=options.content_type,
            etag=hashlib.md5(data, usedforsecurity=False).hexdigest(),
            last_modified=datetime.now(UTC),
            metadata=validate_metadata(options.metadata),
        )
        target.objects[key] = _Stored(
            info=info,
            body=data,
            cache_control=options.cache_control,
            content_disposition=options.content_disposition,
        )
        return info

    async def get(self, bucket: str, key: str) -> BlobObject | None:
        validate_key(key)
        stored = self._bucket(bucket).objects.get(key)
        if stored is None:
            return None
        return BlobObject(
            info=replace(stored.info, metadata=dict(stored.info.metadata)),
            body=stored.body,
        )

    async def head(self, bucket: str, key: str) -> BlobInfo | None:
        validate_key(key)
        found = self._buckets.get(validate_bucket_name(bucket))
        stored = found.objects.get(key) if found else None
        return (
            replace(stored.info, metadata=dict(stored.info.metadata))
            if stored
            else None
        )

    async def exists(self, bucket: str, key: str) -> bool:
        return await self.head(bucket, key) is not None

    async def delete(self, bucket: str, key: str) -> None:
        validate_key(key)
        found = self._buckets.get(validate_bucket_name(bucket))
        if found is not None:  # missing bucket → no-op
            found.objects.pop(key, None)

    async def delete_many(self, bucket: str, keys: Sequence[str]) -> None:
        unique = validate_keys(keys)
        found = self._buckets.get(validate_bucket_name(bucket))
        if found is None:  # missing bucket → no-op
            return
        for key in unique:
            found.objects.pop(key, None)

    async def copy(self, bucket: str, source_key: str, target_key: str) -> None:
        validate_key(source_key)
        validate_key(target_key)
        target = self._bucket(bucket)
        source = target.objects.get(source_key)
        if source is None:
            raise BlobNotFoundError(f'Blob not found: {bucket}/{source_key}')
        target.objects[target_key] = _Stored(
            info=replace(
                source.info,
                key=target_key,
                last_modified=datetime.now(UTC),
                metadata=dict(source.info.metadata),
            ),
            body=source.body,
            cache_control=source.cache_control,
            content_disposition=source.content_disposition,
        )

    async def presign(
        self, bucket: str, key: str, options: BlobPresignOptions | None = None
    ) -> str:
        options = options or BlobPresignOptions()
        validate_bucket_name(bucket)
        validate_key(key)
        expires = resolve_presign_expires(options, self._presign_expires)
        query: dict[str, str] = {'method': options.method, 'expires_in': str(expires)}
        if options.method == 'PUT' and options.content_type:
            query['content_type'] = options.content_type
        if options.method == 'GET' and options.download_name:
            query['response_content_disposition'] = attachment_disposition(
                options.download_name
            )
        return f'memory://{bucket}/{quote(key)}?{urlencode(query)}'

    async def list(
        self, bucket: str, options: BlobListOptions | None = None
    ) -> BlobPage:
        options = validate_list_options(options)
        target = self._bucket(bucket)
        keys = sorted(
            k
            for k in target.objects
            if not options.prefix or k.startswith(options.prefix)
        )
        if options.cursor:
            keys = [k for k in keys if k > options.cursor]
        page_keys = keys[: options.limit]
        items = [
            replace(
                target.objects[k].info, metadata=dict(target.objects[k].info.metadata)
            )
            for k in page_keys
        ]
        next_cursor = page_keys[-1] if len(keys) > options.limit else None
        return BlobPage(items=items, next_cursor=next_cursor)
