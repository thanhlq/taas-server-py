"""In-memory fake of the google-cloud-storage surface used by GcpBlobAdapter (raises google.api_core errors)."""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from google.api_core import exceptions as gexc


@dataclass
class _Record:
    data: bytes
    content_type: str | None
    metadata: dict[str, str] | None
    cache_control: str | None
    content_disposition: str | None
    etag: str
    updated: datetime


class FakeBlob:
    def __init__(self, bucket: FakeBucket, name: str) -> None:
        self.bucket = bucket
        self.name = name
        self.metadata: dict[str, str] | None = None
        self.cache_control: str | None = None
        self.content_disposition: str | None = None
        self.content_type: str | None = None
        self.size: int | None = None
        self.etag: str | None = None
        self.updated: datetime | None = None

    def load(self, record: _Record) -> FakeBlob:
        self.metadata = dict(record.metadata) if record.metadata else None
        self.cache_control = record.cache_control
        self.content_disposition = record.content_disposition
        self.content_type = record.content_type
        self.size = len(record.data)
        self.etag = record.etag
        self.updated = record.updated
        return self

    def upload_from_string(self, data: bytes, content_type: str | None = None) -> None:
        objects = self.bucket.objects_or_raise()
        record = _Record(
            data=data,
            content_type=content_type,
            metadata=dict(self.metadata) if self.metadata else None,
            cache_control=self.cache_control,
            content_disposition=self.content_disposition,
            etag=base64.b64encode(
                hashlib.md5(data, usedforsecurity=False).digest()
            ).decode(),
            updated=datetime.now(UTC),
        )
        objects[self.name] = record
        self.load(record)

    def download_as_bytes(self) -> bytes:
        record = self.bucket.objects_or_raise().get(self.name)
        if record is None:
            raise gexc.NotFound('No such object')
        return record.data

    def exists(self) -> bool:
        return self.name in self.bucket.client.store.get(self.bucket.name, {})

    def delete(self) -> None:
        if self.bucket.objects_or_raise().pop(self.name, None) is None:
            raise gexc.NotFound('No such object')

    def generate_signed_url(self, **kwargs: Any) -> str:
        self.bucket.client.signed.append(kwargs)
        return f'https://storage.googleapis.com/{self.bucket.name}/{self.name}?X-Goog-Signature=fake'


class FakeBucket:
    def __init__(self, client: FakeGcsClient, name: str) -> None:
        self.client = client
        self.name = name
        self.iam_configuration = SimpleNamespace(
            uniform_bucket_level_access_enabled=False,
            public_access_prevention='inherited',
        )

    def objects_or_raise(self) -> dict[str, _Record]:
        if self.name not in self.client.store:
            raise gexc.NotFound(f'No such bucket: {self.name}')
        return self.client.store[self.name]

    def exists(self) -> bool:
        return self.name in self.client.store

    def delete(self, force: bool = False) -> None:
        objects = self.objects_or_raise()
        if objects and not force:
            raise gexc.Conflict('The bucket you tried to delete is not empty.')
        del self.client.store[self.name]

    def blob(self, name: str) -> FakeBlob:
        return FakeBlob(self, name)

    def get_blob(self, name: str) -> FakeBlob | None:
        record = self.client.store.get(self.name, {}).get(name)
        return None if record is None else FakeBlob(self, name).load(record)

    def delete_blobs(
        self, blobs: list[FakeBlob], on_error: Callable[[FakeBlob], None] | None = None
    ) -> None:
        self.client.delete_batches.append(len(blobs))
        for blob in blobs:
            try:
                blob.delete()
            except gexc.NotFound:
                if on_error is None:
                    raise
                on_error(blob)

    def copy_blob(
        self, blob: FakeBlob, destination_bucket: FakeBucket, new_name: str
    ) -> FakeBlob:
        record = self.objects_or_raise().get(blob.name)
        if record is None:
            raise gexc.NotFound('No such object')
        destination_bucket.objects_or_raise()[new_name] = _Record(
            **{**record.__dict__, 'updated': datetime.now(UTC)}
        )
        return FakeBlob(destination_bucket, new_name)


class _Iterator:
    def __init__(self, pages: list[list[FakeBlob]], token: str | None) -> None:
        self._pages = pages
        self._token = token
        self.next_page_token: str | None = None

    @property
    def pages(self) -> Iterator[list[FakeBlob]]:
        for page in self._pages:
            self.next_page_token = self._token
            yield page


@dataclass
class FakeGcsClient:
    store: dict[str, dict[str, _Record]] = field(
        default_factory=dict[str, dict[str, _Record]]
    )
    foreign_buckets: set[str] = field(default_factory=set[str])
    created: list[tuple[str, str, Any]] = field(
        default_factory=list[tuple[str, str, Any]]
    )
    signed: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    delete_batches: list[int] = field(default_factory=list[int])
    closed: bool = False

    def bucket(self, name: str) -> FakeBucket:
        return FakeBucket(self, name)

    def create_bucket(
        self, bucket: FakeBucket, location: str | None = None
    ) -> FakeBucket:
        if bucket.name in self.store or bucket.name in self.foreign_buckets:
            raise gexc.Conflict(
                'Your previous request to create the named bucket succeeded and you already own it.'
            )
        self.created.append((bucket.name, location or '', bucket.iam_configuration))
        self.store[bucket.name] = {}
        return bucket

    def get_bucket(self, name: str) -> FakeBucket:
        if name in self.foreign_buckets:
            raise gexc.Forbidden('no access')
        if name not in self.store:
            raise gexc.NotFound('No such bucket')
        return FakeBucket(self, name)

    def list_blobs(
        self,
        bucket_name: str,
        prefix: str | None = None,
        max_results: int | None = None,
        page_token: str | None = None,
    ) -> _Iterator:
        bucket = self.bucket(bucket_name)
        objects = bucket.objects_or_raise()
        keys = sorted(k for k in objects if not prefix or k.startswith(prefix))
        if page_token:
            keys = [k for k in keys if k > page_token]
        limit = max_results or len(keys)
        page = keys[:limit]
        token = page[-1] if len(keys) > limit else None
        return _Iterator([[FakeBlob(bucket, k).load(objects[k]) for k in page]], token)

    def close(self) -> None:
        self.closed = True
