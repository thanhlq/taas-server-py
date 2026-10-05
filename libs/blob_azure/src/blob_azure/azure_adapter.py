"""`AzureBlobAdapter`: Azure Blob Storage (`azure-storage-blob` aio). A bucket is a container of the account."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from azure.core.exceptions import AzureError, ResourceExistsError, ResourceNotFoundError
from azure.storage.blob import BlobSasPermissions, ContentSettings, generate_blob_sas
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

DELETE_BATCH_SIZE: Final[int] = 256
"""Azure blob batch limit (256 sub-requests)."""
COPY_TIMEOUT_SECONDS: Final[float] = 300.0
_CONTAINER_MISSING: Final[str] = 'ContainerNotFound'


@dataclass
class AzureBlobSettings:
    """`BLOB_AZURE_CONNECTION_STRING`, or `BLOB_AZURE_ACCOUNT_NAME` + `BLOB_AZURE_ACCOUNT_KEY` (SAS needs the key)."""

    BLOB_AZURE_CONNECTION_STRING: str = field(
        default_factory=get_env('BLOB_AZURE_CONNECTION_STRING', '')
    )
    BLOB_AZURE_ACCOUNT_NAME: str = field(
        default_factory=get_env('BLOB_AZURE_ACCOUNT_NAME', '')
    )
    BLOB_AZURE_ACCOUNT_KEY: str = field(
        default_factory=get_env('BLOB_AZURE_ACCOUNT_KEY', '')
    )

    def connection_values(self) -> dict[str, str]:
        """`Key=Value;…` pairs of the connection string."""
        values: dict[str, str] = {}
        for part in self.BLOB_AZURE_CONNECTION_STRING.split(';'):
            name, sep, value = part.partition('=')
            if sep and name.strip():
                values[name.strip()] = value.strip()
        return values

    @property
    def account_name(self) -> str | None:
        return (
            self.BLOB_AZURE_ACCOUNT_NAME.strip()
            or self.connection_values().get('AccountName')
            or None
        )

    @property
    def account_key(self) -> str | None:
        return (
            self.BLOB_AZURE_ACCOUNT_KEY.strip()
            or self.connection_values().get('AccountKey')
            or None
        )


def _error_code(error: BaseException) -> str:
    code = getattr(error, 'error_code', None)
    return str(getattr(code, 'value', code) or '')


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _info(bucket: str, key: str, props: Any) -> BlobInfo:
    content_settings = getattr(props, 'content_settings', None)
    return BlobInfo(
        bucket=bucket,
        key=key,
        size=int(getattr(props, 'size', 0) or 0),
        content_type=getattr(content_settings, 'content_type', None) or None,
        etag=strip_etag(getattr(props, 'etag', None)),
        last_modified=_utc(getattr(props, 'last_modified', None)),
        metadata={
            str(k).lower(): str(v)
            for k, v in (getattr(props, 'metadata', None) or {}).items()
        },
    )


class AzureBlobAdapter(BlobAdapterT):
    """Azure adapter: private containers, SAS presigned URLs (account key required for signing).

    A presigned PUT must send `x-ms-blob-type: BlockBlob` (Azure requirement); `content_type` is not enforced
    by the SAS — the uploader's `Content-Type` header is stored.

    Args:
        settings: defaults to `AzureBlobSettings()` (environment).
        client: an `azure.storage.blob.aio.BlobServiceClient` (or a fake); created lazily otherwise.
        presign_expires: default SAS lifetime (default 900 s; the service passes `BLOB_PRESIGN_EXPIRES` via tenant stores).
    """

    def __init__(
        self,
        settings: AzureBlobSettings | None = None,
        *,
        client: Any | None = None,
        presign_expires: int | None = None,
    ) -> None:
        self._settings = settings or AzureBlobSettings()
        self._client: Any | None = client
        self._owns_client = client is None
        self._presign_expires = presign_expires or DEFAULT_PRESIGN_EXPIRES

    @property
    def provider(self) -> BlobProvider:
        return 'azure'

    def _get_client(self) -> Any:
        if self._client is None:
            from azure.storage.blob.aio import BlobServiceClient

            settings = self._settings
            if settings.BLOB_AZURE_CONNECTION_STRING.strip():
                self._client = BlobServiceClient.from_connection_string(
                    settings.BLOB_AZURE_CONNECTION_STRING
                )
            elif settings.account_name and settings.account_key:
                self._client = BlobServiceClient(
                    account_url=f'https://{settings.account_name}.blob.core.windows.net',
                    credential={
                        'account_name': settings.account_name,
                        'account_key': settings.account_key,
                    },
                )
            else:
                raise BlobProviderError(
                    'azure',
                    'client',
                    'set BLOB_AZURE_CONNECTION_STRING or BLOB_AZURE_ACCOUNT_NAME + BLOB_AZURE_ACCOUNT_KEY',
                )
        return self._client

    async def aclose(self) -> None:
        client, self._client = self._client, None
        if client is not None and self._owns_client:
            await client.close()

    def _container(self, bucket: str) -> Any:
        validate_bucket_name(bucket)
        return self._get_client().get_container_client(bucket)

    def _blob(self, bucket: str, key: str) -> Any:
        validate_bucket_name(bucket)
        validate_key(key)
        return self._get_client().get_blob_client(bucket, key)

    @asynccontextmanager
    async def _errors(self, operation: str) -> AsyncGenerator[None]:
        """Missing container → `BlobNotFoundError`; other SDK errors → `BlobProviderError`."""
        try:
            yield
        except BlobError:
            raise
        except ResourceNotFoundError as e:
            raise BlobNotFoundError(
                f'Not found ({operation}): {_error_code(e) or e}'
            ) from e
        except AzureError as e:
            raise BlobProviderError('azure', operation, e) from e

    # ── buckets (containers) ──────────────────────────────────────────────────

    async def ensure_bucket(self, bucket: str) -> None:
        container = self._container(bucket)
        async with self._errors('ensure_bucket'):
            try:
                await container.create_container()  # no public access
            except ResourceExistsError:
                return  # container names are scoped to the account: it is ours

    async def bucket_exists(self, bucket: str) -> bool:
        container = self._container(bucket)
        async with self._errors('bucket_exists'):
            return bool(await container.exists())

    async def delete_bucket(self, bucket: str) -> None:
        container = self._container(bucket)
        async with self._errors('delete_bucket'):
            try:
                async for _blob in container.list_blobs(results_per_page=1):
                    raise BlobConflictError(f'Bucket not empty: {bucket}')
                await container.delete_container()
            except ResourceNotFoundError:
                return

    # ── objects ───────────────────────────────────────────────────────────────

    async def put(
        self,
        bucket: str,
        key: str,
        body: BlobBody,
        options: BlobPutOptions | None = None,
    ) -> BlobInfo:
        options = options or BlobPutOptions()
        blob = self._blob(bucket, key)
        data = body_to_bytes(body)
        metadata = validate_metadata(options.metadata)
        content_settings = ContentSettings(
            content_type=options.content_type,
            cache_control=options.cache_control,
            content_disposition=options.content_disposition,
        )
        async with self._errors('put'):
            response = await blob.upload_blob(
                data,
                overwrite=True,
                content_settings=content_settings,
                metadata=metadata or None,
            )
        return BlobInfo(
            bucket=bucket,
            key=key,
            size=len(data),
            content_type=options.content_type,
            etag=strip_etag(response.get('etag')),
            last_modified=_utc(response.get('last_modified')),
            metadata=metadata,
        )

    async def get(self, bucket: str, key: str) -> BlobObject | None:
        blob = self._blob(bucket, key)
        async with self._errors('get'):
            try:
                downloader = await blob.download_blob()
            except ResourceNotFoundError as e:
                if _error_code(e) == _CONTAINER_MISSING:
                    raise
                return None
            data: bytes = await downloader.readall()
        return BlobObject(info=_info(bucket, key, downloader.properties), body=data)

    async def head(self, bucket: str, key: str) -> BlobInfo | None:
        blob = self._blob(bucket, key)
        async with self._errors('head'):
            try:
                props = await blob.get_blob_properties()
            except ResourceNotFoundError:
                return None  # HEAD: a missing container is indistinguishable from a missing blob
        return _info(bucket, key, props)

    async def exists(self, bucket: str, key: str) -> bool:
        blob = self._blob(bucket, key)
        async with self._errors('exists'):
            return bool(await blob.exists())

    async def delete(self, bucket: str, key: str) -> None:
        blob = self._blob(bucket, key)
        async with self._errors('delete'):
            try:
                await blob.delete_blob()
            except ResourceNotFoundError:
                return  # idempotent; missing container → no-op

    async def delete_many(self, bucket: str, keys: Sequence[str]) -> None:
        container = self._container(bucket)
        unique = validate_keys(keys)
        for start in range(0, len(unique), DELETE_BATCH_SIZE):
            batch = unique[start : start + DELETE_BATCH_SIZE]
            failures: list[str] = []
            async with self._errors('delete_many'):
                try:
                    responses = await container.delete_blobs(
                        *batch, raise_on_any_failure=False
                    )
                    async for response in responses:
                        if response.status_code not in (200, 202, 404):
                            failures.append(f'HTTP {response.status_code}')
                except ResourceNotFoundError:
                    return  # missing container → no-op
            if failures:
                raise BlobProviderError(
                    'azure',
                    'delete_many',
                    f'{len(failures)} blob(s) not deleted ({failures[0]})',
                )

    async def copy(self, bucket: str, source_key: str, target_key: str) -> None:
        source = self._blob(bucket, source_key)
        target = self._blob(bucket, target_key)
        async with self._errors('copy'):
            try:
                await source.get_blob_properties()
            except ResourceNotFoundError as e:
                raise BlobNotFoundError(f'Blob not found: {bucket}/{source_key}') from e
            try:
                result = await target.start_copy_from_url(source.url)
            except ResourceNotFoundError as e:
                raise BlobNotFoundError(f'Blob not found: {bucket}/{source_key}') from e
            status = str(result.get('copy_status') or 'success')
            loop = asyncio.get_running_loop()
            deadline = loop.time() + COPY_TIMEOUT_SECONDS
            while status == 'pending':
                if loop.time() > deadline:
                    raise BlobProviderError(
                        'azure', 'copy', f'copy of {source_key} still pending'
                    )
                await asyncio.sleep(0.2)
                props = await target.get_blob_properties()
                status = str(props.copy.status or 'success')
            if status != 'success':
                raise BlobProviderError('azure', 'copy', f'copy status {status}')

    async def presign(
        self, bucket: str, key: str, options: BlobPresignOptions | None = None
    ) -> str:
        options = options or BlobPresignOptions()
        blob = self._blob(bucket, key)
        expires = resolve_presign_expires(options, self._presign_expires)
        account_name, account_key = (
            self._settings.account_name,
            self._settings.account_key,
        )
        if not account_name or not account_key:
            raise BlobProviderError(
                'azure',
                'presign',
                'SAS signing needs BLOB_AZURE_ACCOUNT_KEY (or AccountKey in the connection string)',
            )
        permission = (
            BlobSasPermissions(read=True)
            if options.method == 'GET'
            else BlobSasPermissions(create=True, write=True)
        )
        disposition = (
            attachment_disposition(options.download_name)
            if options.method == 'GET' and options.download_name
            else None
        )
        try:
            sas = generate_blob_sas(
                account_name=account_name,
                container_name=bucket,
                blob_name=key,
                account_key=account_key,
                permission=permission,
                expiry=datetime.now(UTC) + timedelta(seconds=expires),
                content_disposition=disposition,
            )
        except (ValueError, TypeError) as e:
            raise BlobProviderError('azure', 'presign', e) from e
        return f'{blob.url}?{sas}'

    async def list(
        self, bucket: str, options: BlobListOptions | None = None
    ) -> BlobPage:
        container = self._container(bucket)
        options = validate_list_options(options)
        async with self._errors('list'):
            pager = container.list_blobs(
                name_starts_with=options.prefix or None,
                include=['metadata'],
                results_per_page=options.limit,
            ).by_page(continuation_token=options.cursor or None)
            items: list[BlobInfo] = []
            try:
                page = await anext(pager)
                items = [_info(bucket, str(b.name), b) async for b in page]
            except StopAsyncIteration:
                pass
            next_cursor = getattr(pager, 'continuation_token', None)
        items.sort(key=lambda i: i.key.encode('utf-8'))
        return BlobPage(items=items, next_cursor=next_cursor or None)
