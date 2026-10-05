"""In-memory fake of the azure-storage-blob aio surface used by AzureBlobAdapter (raises azure.core errors)."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from urllib.parse import quote

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError


def not_found(code: str) -> ResourceNotFoundError:
    error = ResourceNotFoundError(message=code)
    error.error_code = code  # type: ignore[attr-defined]
    return error


@dataclass
class _Record:
    data: bytes
    content_type: str | None
    cache_control: str | None
    content_disposition: str | None
    metadata: dict[str, str]
    etag: str
    last_modified: datetime
    copy_status: str | None = None


def _props(name: str, record: _Record) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        size=len(record.data),
        content_settings=SimpleNamespace(content_type=record.content_type),
        etag=record.etag,
        last_modified=record.last_modified,
        metadata=dict(record.metadata),
        copy=SimpleNamespace(status=record.copy_status),
    )


class _Downloader:
    def __init__(self, name: str, record: _Record) -> None:
        self.properties = _props(name, record)
        self._data = record.data

    async def readall(self) -> bytes:
        return self._data


class _Page:
    def __init__(self, items: list[SimpleNamespace]) -> None:
        self._items = items

    def __aiter__(self) -> AsyncIterator[SimpleNamespace]:
        async def gen() -> AsyncIterator[SimpleNamespace]:
            for item in self._items:
                yield item

        return gen()


class _Pager:
    def __init__(self, pages: list[list[SimpleNamespace]], token: str | None) -> None:
        self._pages = pages
        self._token = token
        self.continuation_token: str | None = None

    def __aiter__(self) -> _Pager:
        return self

    async def __anext__(self) -> _Page:
        if not self._pages:
            raise StopAsyncIteration
        self.continuation_token = self._token
        return _Page(self._pages.pop(0))


class _ItemPaged:
    def __init__(
        self, container: FakeContainer, prefix: str | None, per_page: int | None
    ) -> None:
        self._container = container
        self._prefix = prefix
        self._per_page = per_page

    def by_page(self, continuation_token: str | None = None) -> _Pager:
        objects = self._container.objects_or_raise()
        keys = sorted(
            k for k in objects if not self._prefix or k.startswith(self._prefix)
        )
        if continuation_token:
            keys = [k for k in keys if k > continuation_token]
        limit = self._per_page or 5000
        page = keys[:limit]
        token = page[-1] if len(keys) > limit else None
        return _Pager([[_props(k, objects[k]) for k in page]], token)

    def __aiter__(self) -> AsyncIterator[SimpleNamespace]:
        async def gen() -> AsyncIterator[SimpleNamespace]:
            objects = self._container.objects_or_raise()
            for key in sorted(objects):
                yield _props(key, objects[key])

        return gen()


class _Responses:
    def __init__(self, statuses: list[int]) -> None:
        self._statuses = statuses

    def __aiter__(self) -> AsyncIterator[SimpleNamespace]:
        async def gen() -> AsyncIterator[SimpleNamespace]:
            for status in self._statuses:
                yield SimpleNamespace(status_code=status)

        return gen()


class FakeContainer:
    def __init__(self, service: FakeBlobServiceClient, name: str) -> None:
        self.service = service
        self.name = name

    def objects_or_raise(self) -> dict[str, _Record]:
        if self.name not in self.service.store:
            raise not_found('ContainerNotFound')
        return self.service.store[self.name]

    async def create_container(self, **kw: Any) -> None:
        if self.name in self.service.store:
            raise ResourceExistsError(message='ContainerAlreadyExists')
        self.service.created.append((self.name, kw))
        self.service.store[self.name] = {}

    async def exists(self) -> bool:
        return self.name in self.service.store

    async def delete_container(self) -> None:
        self.objects_or_raise()
        del self.service.store[self.name]

    def list_blobs(
        self,
        name_starts_with: str | None = None,
        include: list[str] | None = None,
        results_per_page: int | None = None,
    ) -> _ItemPaged:
        return _ItemPaged(self, name_starts_with, results_per_page)

    async def delete_blobs(
        self, *names: str, raise_on_any_failure: bool = True
    ) -> _Responses:
        assert raise_on_any_failure is False
        self.service.delete_batches.append(len(names))
        objects = self.objects_or_raise()
        return _Responses(
            [202 if objects.pop(n, None) is not None else 404 for n in names]
        )


class FakeBlobClient:
    def __init__(
        self, service: FakeBlobServiceClient, container: str, name: str
    ) -> None:
        self.service = service
        self.container = FakeContainer(service, container)
        self.name = name

    @property
    def url(self) -> str:
        return f'https://acct.blob.core.windows.net/{self.container.name}/{quote(self.name)}'

    async def upload_blob(
        self,
        data: bytes,
        overwrite: bool = False,
        content_settings: Any = None,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        assert overwrite is True
        objects = self.container.objects_or_raise()
        record = _Record(
            data=data,
            content_type=content_settings.content_type,
            cache_control=content_settings.cache_control,
            content_disposition=content_settings.content_disposition,
            metadata=dict(metadata or {}),
            etag=f'"0x{hashlib.md5(data, usedforsecurity=False).hexdigest()[:15].upper()}"',
            last_modified=datetime.now(UTC),
        )
        objects[self.name] = record
        return {'etag': record.etag, 'last_modified': record.last_modified}

    def _record(self) -> _Record:
        record = self.container.objects_or_raise().get(self.name)
        if record is None:
            raise not_found('BlobNotFound')
        return record

    async def download_blob(self) -> _Downloader:
        return _Downloader(self.name, self._record())

    async def get_blob_properties(self) -> SimpleNamespace:
        record = self._record()
        props = _props(self.name, record)
        if record.copy_status == 'pending':
            record.copy_status = 'success'  # completes on the next poll
        return props

    async def exists(self) -> bool:
        return self.name in self.service.store.get(self.container.name, {})

    async def delete_blob(self) -> None:
        self._record()
        del self.container.objects_or_raise()[self.name]

    async def start_copy_from_url(self, source_url: str) -> dict[str, Any]:
        prefix = f'https://acct.blob.core.windows.net/{self.container.name}/'
        assert source_url.startswith(prefix)
        from urllib.parse import unquote

        source = self.container.objects_or_raise().get(
            unquote(source_url[len(prefix) :])
        )
        if source is None:
            raise not_found('CannotVerifyCopySource')
        status = 'pending' if self.service.copy_pending else 'success'
        self.container.objects_or_raise()[self.name] = _Record(
            **{**source.__dict__, 'copy_status': status}
        )
        return {'copy_status': status}


@dataclass
class FakeBlobServiceClient:
    store: dict[str, dict[str, _Record]] = field(
        default_factory=dict[str, dict[str, _Record]]
    )
    created: list[tuple[str, dict[str, Any]]] = field(
        default_factory=list[tuple[str, dict[str, Any]]]
    )
    delete_batches: list[int] = field(default_factory=list[int])
    copy_pending: bool = False
    closed: bool = False

    def get_container_client(self, name: str) -> FakeContainer:
        return FakeContainer(self, name)

    def get_blob_client(self, container: str, blob: str) -> FakeBlobClient:
        return FakeBlobClient(self, container, blob)

    async def close(self) -> None:
        self.closed = True
