"""`GcpBlobAdapter`: Google Cloud Storage via the sync `google-cloud-storage` SDK run in `asyncio.to_thread`."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from foundation.blob import (
    DEFAULT_PRESIGN_EXPIRES,
    BlobAdapterT,
    BlobBody,
    BlobConflictError,
    BlobError,
    BlobInfo,
    BlobListOptions,
    BlobNotFoundError,
    BlobObject,
    BlobPage,
    BlobPresignOptions,
    BlobProvider,
    BlobProviderError,
    BlobPutOptions,
    attachment_disposition,
    body_to_bytes,
    validate_metadata,
    resolve_presign_expires,
    strip_etag,
    validate_bucket_name,
    validate_key,
    validate_keys,
    validate_list_options,
)
from foundation.utils.env_utils import get_env
from google.api_core import exceptions as gexc

DELETE_BATCH_SIZE: Final[int] = 1000


@dataclass
class GcpBlobSettings:
    """Credentials come from `GOOGLE_APPLICATION_CREDENTIALS` / ADC (signed URLs need a signing identity)."""

    BLOB_GCP_PROJECT_ID: str = field(default_factory=get_env('BLOB_GCP_PROJECT_ID', ''))
    """GCS project; empty = the project of the credentials."""
    BLOB_GCP_LOCATION: str = field(default_factory=get_env('BLOB_GCP_LOCATION', 'EU'))
    """Location of new buckets."""

    @property
    def project_id(self) -> str | None:
        return (
            self.BLOB_GCP_PROJECT_ID.strip()
            or os.getenv('GOOGLE_CLOUD_PROJECT')
            or None
        )


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _info(bucket: str, key: str, blob: Any) -> BlobInfo:
    return BlobInfo(
        bucket=bucket,
        key=key,
        size=int(blob.size or 0),
        content_type=blob.content_type or None,
        etag=strip_etag(blob.etag),
        last_modified=_utc(blob.updated),
        metadata={str(k).lower(): str(v) for k, v in (blob.metadata or {}).items()},
    )


class GcpBlobAdapter(BlobAdapterT):
    """Google Cloud Storage adapter (uniform bucket-level access, public access prevention enforced).

    Args:
        settings: defaults to `GcpBlobSettings()` (environment).
        client: a `google.cloud.storage.Client` (or a fake with the same surface); created lazily otherwise.
        presign_expires: default signed URL lifetime (default 900 s; the service passes `BLOB_PRESIGN_EXPIRES` via tenant stores).
    """

    def __init__(
        self,
        settings: GcpBlobSettings | None = None,
        *,
        client: Any | None = None,
        presign_expires: int | None = None,
    ) -> None:
        self._settings = settings or GcpBlobSettings()
        self._client: Any | None = client
        self._owns_client = client is None
        self._client_lock = asyncio.Lock()
        self._presign_expires = presign_expires or DEFAULT_PRESIGN_EXPIRES

    @property
    def provider(self) -> BlobProvider:
        return 'gcp'

    async def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        async with self._client_lock:
            if self._client is None:
                from google.cloud import storage

                project = self._settings.project_id
                with self._errors('client'):
                    self._client = await asyncio.to_thread(
                        storage.Client, project=project
                    )
        return self._client

    async def aclose(self) -> None:
        """Close the client this adapter created (an injected client is left open)."""
        if not self._owns_client:
            return
        client, self._client = self._client, None
        close = getattr(client, 'close', None)
        if callable(close):
            await asyncio.to_thread(close)

    @contextmanager
    def _errors(self, operation: str) -> Generator[None]:
        try:
            yield
        except BlobError:
            raise
        except gexc.NotFound as e:
            raise BlobNotFoundError(f'Not found ({operation}): {e}') from e
        except Exception as e:  # google.api_core / google.auth / transport errors
            raise BlobProviderError('gcp', operation, e) from e

    async def _run[T](self, operation: str, fn: Callable[[Any], T]) -> T:
        client = await self._get_client()

        def call() -> T:
            with self._errors(operation):
                return fn(client)

        return await asyncio.to_thread(call)

    # ── buckets ───────────────────────────────────────────────────────────────

    async def ensure_bucket(self, bucket: str) -> None:
        validate_bucket_name(bucket)
        location = self._settings.BLOB_GCP_LOCATION

        def create(client: Any) -> None:
            target = client.bucket(bucket)
            target.iam_configuration.uniform_bucket_level_access_enabled = True
            target.iam_configuration.public_access_prevention = 'enforced'
            try:
                client.create_bucket(target, location=location)
            except gexc.Conflict as e:
                try:
                    client.get_bucket(bucket)  # readable → already ours
                except gexc.Forbidden, gexc.NotFound:
                    raise BlobConflictError(
                        f'Bucket name taken by another project: {bucket}'
                    ) from e

        await self._run('ensure_bucket', create)

    async def bucket_exists(self, bucket: str) -> bool:
        validate_bucket_name(bucket)
        return await self._run(
            'bucket_exists', lambda client: bool(client.bucket(bucket).exists())
        )

    async def delete_bucket(self, bucket: str) -> None:
        validate_bucket_name(bucket)

        def delete(client: Any) -> None:
            try:
                client.bucket(bucket).delete(force=False)
            except gexc.NotFound:
                return
            except gexc.Conflict as e:
                raise BlobConflictError(f'Bucket not empty: {bucket}') from e

        await self._run('delete_bucket', delete)

    # ── objects ───────────────────────────────────────────────────────────────

    async def put(
        self,
        bucket: str,
        key: str,
        body: BlobBody,
        options: BlobPutOptions | None = None,
    ) -> BlobInfo:
        options = options or BlobPutOptions()
        validate_bucket_name(bucket)
        validate_key(key)
        data = body_to_bytes(body)
        metadata = validate_metadata(options.metadata)

        def upload(client: Any) -> BlobInfo:
            blob = client.bucket(bucket).blob(key)
            blob.metadata = metadata or None
            blob.cache_control = options.cache_control
            blob.content_disposition = options.content_disposition
            blob.upload_from_string(data, content_type=options.content_type)
            info = _info(bucket, key, blob)
            # The upload response carries the stored properties; fall back to what was sent.
            return BlobInfo(
                bucket=bucket,
                key=key,
                size=info.size or len(data),
                content_type=info.content_type or options.content_type,
                etag=info.etag,
                last_modified=info.last_modified,
                metadata=info.metadata or metadata,
            )

        return await self._run('put', upload)

    async def get(self, bucket: str, key: str) -> BlobObject | None:
        validate_bucket_name(bucket)
        validate_key(key)

        def download(client: Any) -> BlobObject | None:
            target = client.bucket(bucket)
            blob = target.get_blob(key)
            if blob is None:
                if not target.exists():  # only on a miss: a missing bucket raises
                    raise BlobNotFoundError(f'Bucket not found: {bucket}')
                return None
            try:
                data: bytes = blob.download_as_bytes()
            except gexc.NotFound:
                return None
            return BlobObject(info=_info(bucket, key, blob), body=data)

        return await self._run('get', download)

    async def head(self, bucket: str, key: str) -> BlobInfo | None:
        validate_bucket_name(bucket)
        validate_key(key)

        def head(client: Any) -> BlobInfo | None:
            blob = client.bucket(bucket).get_blob(key)
            return None if blob is None else _info(bucket, key, blob)

        return await self._run('head', head)

    async def exists(self, bucket: str, key: str) -> bool:
        validate_bucket_name(bucket)
        validate_key(key)
        return await self._run(
            'exists', lambda client: bool(client.bucket(bucket).blob(key).exists())
        )

    async def delete(self, bucket: str, key: str) -> None:
        validate_bucket_name(bucket)
        validate_key(key)

        def delete(client: Any) -> None:
            try:
                client.bucket(bucket).blob(key).delete()
            except gexc.NotFound:
                return

        await self._run('delete', delete)

    async def delete_many(self, bucket: str, keys: Sequence[str]) -> None:
        validate_bucket_name(bucket)
        unique = validate_keys(keys)
        if not unique:
            return

        def delete_all(client: Any) -> None:
            target = client.bucket(bucket)
            for start in range(0, len(unique), DELETE_BATCH_SIZE):
                batch = unique[start : start + DELETE_BATCH_SIZE]
                # `on_error` receives the blobs that were already missing (404); other errors raise.
                target.delete_blobs(
                    [target.blob(k) for k in batch], on_error=lambda _blob: None
                )

        await self._run('delete_many', delete_all)

    async def copy(self, bucket: str, source_key: str, target_key: str) -> None:
        validate_bucket_name(bucket)
        validate_key(source_key)
        validate_key(target_key)

        def copy(client: Any) -> None:
            target = client.bucket(bucket)
            try:
                target.copy_blob(target.blob(source_key), target, target_key)
            except gexc.NotFound as e:
                raise BlobNotFoundError(f'Blob not found: {bucket}/{source_key}') from e

        await self._run('copy', copy)

    async def presign(
        self, bucket: str, key: str, options: BlobPresignOptions | None = None
    ) -> str:
        options = options or BlobPresignOptions()
        validate_bucket_name(bucket)
        validate_key(key)
        expires = resolve_presign_expires(options, self._presign_expires)
        kwargs: dict[str, Any] = {
            'version': 'v4',
            'expiration': timedelta(seconds=expires),
            'method': options.method,
        }
        if options.method == 'PUT' and options.content_type:
            kwargs['content_type'] = options.content_type
        if options.method == 'GET' and options.download_name:
            kwargs['response_disposition'] = attachment_disposition(
                options.download_name
            )

        def sign(client: Any) -> str:
            return str(client.bucket(bucket).blob(key).generate_signed_url(**kwargs))

        return await self._run('presign', sign)

    async def list(
        self, bucket: str, options: BlobListOptions | None = None
    ) -> BlobPage:
        validate_bucket_name(bucket)
        options = validate_list_options(options)

        def list_page(client: Any) -> BlobPage:
            iterator = client.list_blobs(
                bucket,
                prefix=options.prefix or None,
                max_results=options.limit,
                page_token=options.cursor or None,
            )
            page = next(iter(iterator.pages), None)
            blobs: list[Any] = [] if page is None else [*page]
            items = sorted(
                (_info(bucket, str(b.name), b) for b in blobs),
                key=lambda i: i.key.encode('utf-8'),
            )
            return BlobPage(items=items, next_cursor=iterator.next_page_token or None)

        return await self._run('list', list_page)
