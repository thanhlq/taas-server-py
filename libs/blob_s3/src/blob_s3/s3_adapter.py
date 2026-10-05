"""`S3BlobAdapter`: AWS S3, Cloudflare R2 and RustFS through `aiobotocore` (async)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Final

from aiobotocore.config import AioConfig
from aiobotocore.session import get_session
from botocore.exceptions import BotoCoreError, ClientError
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

from .s3_settings import S3BlobSettings

DELETE_BATCH_SIZE: Final[int] = 1000
_MISSING_KEY_CODES: Final[frozenset[str]] = frozenset({'NoSuchKey', 'NotFound', '404'})
_MISSING_BUCKET_CODES: Final[frozenset[str]] = frozenset({'NoSuchBucket'})


def _error_code(error: ClientError) -> str:
    return str(error.response.get('Error', {}).get('Code', ''))


def _status(error: ClientError) -> int:
    return int(error.response.get('ResponseMetadata', {}).get('HTTPStatusCode', 0) or 0)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class S3BlobAdapter(BlobAdapterT):
    """S3 compatible adapter.

    Args:
        settings: defaults to `S3BlobSettings()` (environment).
        client: an already-entered aiobotocore S3 client (tests / shared client); not closed by `aclose`.
        presign_expires: default presigned URL lifetime (default 900 s; the service passes `BLOB_PRESIGN_EXPIRES` via tenant stores).
    """

    def __init__(
        self,
        settings: S3BlobSettings | None = None,
        *,
        client: Any | None = None,
        presign_expires: int | None = None,
    ) -> None:
        self._settings = settings or S3BlobSettings()
        self._client: Any | None = client
        self._exit_stack: AsyncExitStack | None = None
        self._client_lock = asyncio.Lock()
        self._presign_expires = presign_expires or DEFAULT_PRESIGN_EXPIRES

    @property
    def provider(self) -> BlobProvider:
        return 's3'

    @property
    def settings(self) -> S3BlobSettings:
        return self._settings

    def client_config(self) -> AioConfig:
        """SigV4, path-style when configured, checksums only when required (R2 / RustFS compatible)."""
        return AioConfig(
            signature_version='s3v4',
            s3={
                'addressing_style': 'path'
                if self._settings.force_path_style
                else 'auto'
            },
            request_checksum_calculation='when_required',
            response_checksum_validation='when_required',
        )

    async def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        async with self._client_lock:
            if self._client is None:
                settings = self._settings
                credentials: dict[str, str] = {}
                if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
                    credentials = {
                        'aws_access_key_id': settings.AWS_ACCESS_KEY_ID,
                        'aws_secret_access_key': settings.AWS_SECRET_ACCESS_KEY,
                    }
                stack = AsyncExitStack()
                self._client = await stack.enter_async_context(
                    get_session().create_client(
                        's3',
                        endpoint_url=settings.endpoint_url,
                        region_name=settings.AWS_REGION,
                        config=self.client_config(),
                        **credentials,
                    )
                )
                self._exit_stack = stack
        return self._client

    async def aclose(self) -> None:
        if self._exit_stack is not None:
            stack, self._exit_stack = self._exit_stack, None
            self._client = None
            await stack.aclose()

    @asynccontextmanager
    async def _errors(self, operation: str) -> AsyncGenerator[None]:
        """Translate SDK errors: missing bucket → `BlobNotFoundError`, others → `BlobProviderError`."""
        try:
            yield
        except ClientError as e:
            if _error_code(e) in _MISSING_BUCKET_CODES:
                raise BlobNotFoundError(f'Bucket not found ({operation}): {e}') from e
            raise BlobProviderError('s3', operation, e) from e
        except BotoCoreError as e:
            raise BlobProviderError('s3', operation, e) from e

    # ── buckets ───────────────────────────────────────────────────────────────

    async def ensure_bucket(self, bucket: str) -> None:
        validate_bucket_name(bucket)
        client = await self._get_client()
        params: dict[str, Any] = {'Bucket': bucket}
        region = self._settings.AWS_REGION
        if self._settings.endpoint_url is None and region not in (
            'us-east-1',
            'auto',
            '',
        ):
            params['CreateBucketConfiguration'] = {'LocationConstraint': region}
        async with self._errors('ensure_bucket'):
            try:
                await client.create_bucket(**params)
            except ClientError as e:
                code = _error_code(e)
                if code == 'BucketAlreadyOwnedByYou':
                    return
                if code == 'BucketAlreadyExists':
                    try:  # S3 compatible servers may answer this for their own buckets: readable → ours
                        await client.head_bucket(Bucket=bucket)
                    except ClientError:
                        raise BlobConflictError(
                            f'Bucket name taken by another account: {bucket}'
                        ) from e
                    return
                raise

    async def bucket_exists(self, bucket: str) -> bool:
        validate_bucket_name(bucket)
        client = await self._get_client()
        async with self._errors('bucket_exists'):
            try:
                await client.head_bucket(Bucket=bucket)
            except ClientError as e:
                if _status(e) == 404 or _error_code(e) in (
                    _MISSING_BUCKET_CODES | {'NotFound', '404'}
                ):
                    return False
                raise
        return True

    async def delete_bucket(self, bucket: str) -> None:
        validate_bucket_name(bucket)
        client = await self._get_client()
        try:
            await client.delete_bucket(Bucket=bucket)
        except ClientError as e:
            code = _error_code(e)
            if code in _MISSING_BUCKET_CODES:
                return
            if code == 'BucketNotEmpty':
                raise BlobConflictError(f'Bucket not empty: {bucket}') from e
            raise BlobProviderError('s3', 'delete_bucket', e) from e
        except BotoCoreError as e:
            raise BlobProviderError('s3', 'delete_bucket', e) from e

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
        params: dict[str, Any] = {
            'Bucket': bucket,
            'Key': key,
            'Body': data,
            'ContentType': options.content_type,
            'Metadata': metadata,
        }
        if options.cache_control:
            params['CacheControl'] = options.cache_control
        if options.content_disposition:
            params['ContentDisposition'] = options.content_disposition
        client = await self._get_client()
        async with self._errors('put'):
            response = await client.put_object(**params)
        return BlobInfo(
            bucket=bucket,
            key=key,
            size=len(data),
            content_type=options.content_type,
            etag=strip_etag(response.get('ETag')),
            last_modified=None,  # PutObject does not return it
            metadata=metadata,
        )

    def _info(self, bucket: str, key: str, response: Mapping[str, Any]) -> BlobInfo:
        return BlobInfo(
            bucket=bucket,
            key=key,
            size=int(response.get('ContentLength', 0) or 0),
            content_type=response.get('ContentType') or None,
            etag=strip_etag(response.get('ETag')),
            last_modified=_utc(response.get('LastModified')),
            metadata={
                str(k).lower(): str(v)
                for k, v in (response.get('Metadata') or {}).items()
            },
        )

    async def get(self, bucket: str, key: str) -> BlobObject | None:
        validate_bucket_name(bucket)
        validate_key(key)
        client = await self._get_client()
        async with self._errors('get'):
            try:
                response = await client.get_object(Bucket=bucket, Key=key)
            except ClientError as e:
                if _error_code(e) in _MISSING_KEY_CODES:
                    return None
                raise
            async with response['Body'] as stream:
                data: bytes = await stream.read()
        return BlobObject(info=self._info(bucket, key, response), body=data)

    async def head(self, bucket: str, key: str) -> BlobInfo | None:
        validate_bucket_name(bucket)
        validate_key(key)
        client = await self._get_client()
        async with self._errors('head'):
            try:
                response = await client.head_object(Bucket=bucket, Key=key)
            except ClientError as e:
                # HEAD has no error body: a missing bucket is indistinguishable from a missing key.
                if _status(e) == 404 or _error_code(e) in _MISSING_KEY_CODES:
                    return None
                raise
        return self._info(bucket, key, response)

    async def exists(self, bucket: str, key: str) -> bool:
        return await self.head(bucket, key) is not None

    async def delete(self, bucket: str, key: str) -> None:
        validate_bucket_name(bucket)
        validate_key(key)
        client = await self._get_client()
        async with self._errors('delete'):
            try:
                await client.delete_object(Bucket=bucket, Key=key)
            except ClientError as e:
                if _error_code(e) in _MISSING_KEY_CODES | _MISSING_BUCKET_CODES:
                    return  # idempotent; missing bucket → no-op
                raise

    async def delete_many(self, bucket: str, keys: Sequence[str]) -> None:
        validate_bucket_name(bucket)
        unique = validate_keys(keys)
        if not unique:
            return
        client = await self._get_client()
        for start in range(0, len(unique), DELETE_BATCH_SIZE):
            batch = unique[start : start + DELETE_BATCH_SIZE]
            async with self._errors('delete_many'):
                try:
                    response = await client.delete_objects(
                        Bucket=bucket,
                        Delete={'Objects': [{'Key': k} for k in batch], 'Quiet': True},
                    )
                except ClientError as e:
                    if _error_code(e) in _MISSING_BUCKET_CODES:
                        return  # missing bucket → no-op
                    raise
            errors = [
                e
                for e in response.get('Errors') or []
                if e.get('Code') not in _MISSING_KEY_CODES
            ]
            if errors:
                first = errors[0]
                raise BlobProviderError(
                    's3',
                    'delete_many',
                    f'{len(errors)} key(s) not deleted, e.g. {first.get("Key")}: {first.get("Code")} {first.get("Message")}',
                )

    async def copy(self, bucket: str, source_key: str, target_key: str) -> None:
        validate_bucket_name(bucket)
        validate_key(source_key)
        validate_key(target_key)
        client = await self._get_client()
        async with self._errors('copy'):
            try:
                await client.copy_object(
                    Bucket=bucket,
                    Key=target_key,
                    CopySource={'Bucket': bucket, 'Key': source_key},
                    MetadataDirective='COPY',
                )
            except ClientError as e:
                code = _error_code(e)
                if code in _MISSING_KEY_CODES or (
                    _status(e) == 404 and code not in _MISSING_BUCKET_CODES
                ):
                    raise BlobNotFoundError(
                        f'Blob not found: {bucket}/{source_key}'
                    ) from e
                raise

    async def presign(
        self, bucket: str, key: str, options: BlobPresignOptions | None = None
    ) -> str:
        options = options or BlobPresignOptions()
        validate_bucket_name(bucket)
        validate_key(key)
        expires = resolve_presign_expires(options, self._presign_expires)
        params: dict[str, Any] = {'Bucket': bucket, 'Key': key}
        if options.method == 'GET':
            method = 'get_object'
            if options.download_name:
                params['ResponseContentDisposition'] = attachment_disposition(
                    options.download_name
                )
        else:
            method = 'put_object'
            if options.content_type:
                params['ContentType'] = options.content_type
        client = await self._get_client()
        async with self._errors('presign'):
            url: str = await client.generate_presigned_url(
                method, Params=params, ExpiresIn=expires
            )
        return url

    async def list(
        self, bucket: str, options: BlobListOptions | None = None
    ) -> BlobPage:
        validate_bucket_name(bucket)
        options = validate_list_options(options)
        params: dict[str, Any] = {'Bucket': bucket, 'MaxKeys': options.limit}
        if options.prefix:
            params['Prefix'] = options.prefix
        if options.cursor:
            params['ContinuationToken'] = options.cursor
        client = await self._get_client()
        async with self._errors('list'):
            response = await client.list_objects_v2(**params)
        items = [
            BlobInfo(
                bucket=bucket,
                key=str(item['Key']),
                size=int(item.get('Size', 0) or 0),
                content_type=None,  # not returned by ListObjectsV2
                etag=strip_etag(item.get('ETag')),
                last_modified=_utc(item.get('LastModified')),
            )
            for item in response.get('Contents') or []
        ]
        items.sort(key=lambda info: info.key.encode('utf-8'))
        next_cursor = (
            response.get('NextContinuationToken')
            if response.get('IsTruncated')
            else None
        )
        return BlobPage(items=items, next_cursor=next_cursor or None)
