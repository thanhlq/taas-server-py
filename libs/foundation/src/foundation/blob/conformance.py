"""Shared behaviour suite for `BlobAdapterT` implementations (contract §7).

Framework-free: each check is `async def check(ctx) -> None` using `assert`. Test modules parametrize over
`BLOB_ADAPTER_CHECKS` and turn `BlobCheckSkipped` into a skip, e.g.::

    @pytest.mark.parametrize('name', sorted(BLOB_ADAPTER_CHECKS))
    async def test_behaviour(name, ctx):
        try:
            await BLOB_ADAPTER_CHECKS[name](ctx)
        except BlobCheckSkipped as e:
            pytest.skip(str(e))

`ctx.bucket` must exist and be empty; buckets from `ctx.new_bucket_name()` are deleted by the check itself
(callers should still clean up every name they handed out). Presigned URL checks need `ctx.http`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

from .blob_errors import BlobConflictError, BlobNotFoundError, BlobValidationError
from .blob_interfaces import BlobAdapterT
from .blob_types import (
    DEFAULT_CONTENT_TYPE,
    BlobListOptions,
    BlobPresignOptions,
    BlobPutOptions,
)


class BlobCheckSkipped(Exception):  # noqa: N818 - mirrors pytest.skip
    """Raised by a check that cannot run in this context (e.g. no HTTP client for presigned URLs)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class BlobHttpResponse:
    status: int
    headers: Mapping[str, str]
    """Header names lower-case."""
    body: bytes


class BlobHttpClient(Protocol):
    """Unauthenticated HTTP call used to exercise presigned URLs (e.g. wraps `httpx.AsyncClient`)."""

    def __call__(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        content: bytes | None = None,
    ) -> Awaitable[BlobHttpResponse]: ...


@dataclass(slots=True, kw_only=True)
class BlobSuiteContext:
    adapter: BlobAdapterT
    bucket: str
    """An existing, empty bucket."""
    new_bucket_name: Callable[[], str]
    """A fresh (not yet created) valid bucket name."""
    http: BlobHttpClient | None = None
    """Needed by the presigned URL checks."""
    created_buckets: list[str] = field(default_factory=list[str])


async def check_bucket_lifecycle(ctx: BlobSuiteContext) -> None:
    adapter = ctx.adapter
    name = ctx.new_bucket_name()
    ctx.created_buckets.append(name)
    try:
        assert await adapter.bucket_exists(name) is False
        await adapter.ensure_bucket(name)
        assert await adapter.bucket_exists(name) is True
        await adapter.ensure_bucket(name)  # idempotent
        await adapter.put(name, 'a.txt', b'a')
        try:
            await adapter.delete_bucket(name)
            raise AssertionError(
                'deleting a non-empty bucket must raise BlobConflictError'
            )
        except BlobConflictError:
            pass
        await adapter.delete(name, 'a.txt')
        await adapter.delete_bucket(name)
        assert await adapter.bucket_exists(name) is False
        await adapter.delete_bucket(name)  # missing → no error
    finally:
        if await adapter.bucket_exists(name):
            page = await adapter.list(name)
            await adapter.delete_many(name, [item.key for item in page.items])
            await adapter.delete_bucket(name)


async def check_put_get_head_exists(ctx: BlobSuiteContext) -> None:
    adapter, bucket = ctx.adapter, ctx.bucket
    info = await adapter.put(bucket, 'docs/a.bin', b'\x00\x01hello')
    assert info.bucket == bucket
    assert info.key == 'docs/a.bin'
    assert info.size == 7
    assert info.content_type == DEFAULT_CONTENT_TYPE
    assert info.etag is None or '"' not in info.etag

    obj = await adapter.get(bucket, 'docs/a.bin')
    assert obj is not None
    assert obj.body == b'\x00\x01hello'
    assert obj.info.size == 7
    assert obj.info.key == 'docs/a.bin'
    assert obj.info.content_type == DEFAULT_CONTENT_TYPE
    assert obj.info.etag and '"' not in obj.info.etag
    assert (
        obj.info.last_modified is not None
        and obj.info.last_modified.utcoffset() is not None
    )
    assert obj.info.last_modified.utcoffset().total_seconds() == 0  # pyright: ignore[reportOptionalMemberAccess]

    head = await adapter.head(bucket, 'docs/a.bin')
    assert head is not None
    assert head.size == 7
    assert head.etag == obj.info.etag
    assert await adapter.exists(bucket, 'docs/a.bin') is True

    assert await adapter.get(bucket, 'docs/missing.bin') is None
    assert await adapter.head(bucket, 'docs/missing.bin') is None
    assert await adapter.exists(bucket, 'docs/missing.bin') is False


async def check_put_str_is_utf8(ctx: BlobSuiteContext) -> None:
    adapter, bucket = ctx.adapter, ctx.bucket
    info = await adapter.put(
        bucket,
        'text/héllo.txt',
        'héllo wörld',
        BlobPutOptions(content_type='text/plain'),
    )
    assert info.size == len('héllo wörld'.encode())
    obj = await adapter.get(bucket, 'text/héllo.txt')
    assert obj is not None
    assert obj.body == 'héllo wörld'.encode()
    assert obj.info.key == 'text/héllo.txt'


async def check_overwrite(ctx: BlobSuiteContext) -> None:
    adapter, bucket = ctx.adapter, ctx.bucket
    await adapter.put(
        bucket, 'over.txt', b'first version', BlobPutOptions(content_type='text/plain')
    )
    await adapter.put(
        bucket, 'over.txt', b'second', BlobPutOptions(content_type='application/json')
    )
    obj = await adapter.get(bucket, 'over.txt')
    assert obj is not None
    assert obj.body == b'second'
    assert obj.info.size == 6
    assert obj.info.content_type == 'application/json'


async def check_metadata_and_content_type(ctx: BlobSuiteContext) -> None:
    adapter, bucket = ctx.adapter, ctx.bucket
    options = BlobPutOptions(
        content_type='application/json',
        metadata={'Owner': 'alice', 'project_id': 'p1'},
        cache_control='max-age=60',
        content_disposition='inline',
    )
    info = await adapter.put(bucket, 'meta.json', b'{}', options)
    assert info.content_type == 'application/json'
    assert info.metadata == {'owner': 'alice', 'project_id': 'p1'}
    head = await adapter.head(bucket, 'meta.json')
    assert head is not None
    assert head.content_type == 'application/json'
    assert head.metadata == {'owner': 'alice', 'project_id': 'p1'}
    obj = await adapter.get(bucket, 'meta.json')
    assert obj is not None
    assert obj.info.metadata == {'owner': 'alice', 'project_id': 'p1'}
    for bad in ('project-id', '1st', 'has space', '', 'x' * 64):
        try:
            await adapter.put(
                bucket, 'meta-bad.json', b'{}', BlobPutOptions(metadata={bad: 'v'})
            )
            raise AssertionError(f'metadata key {bad!r} must raise BlobValidationError')
        except BlobValidationError:
            pass
    assert await adapter.exists(bucket, 'meta-bad.json') is False


async def check_list_paging(ctx: BlobSuiteContext) -> None:
    adapter, bucket = ctx.adapter, ctx.bucket
    keys = [f'list/item-{i}.txt' for i in (3, 0, 4, 1, 2)]
    for key in keys:
        await adapter.put(bucket, key, key)
    await adapter.put(bucket, 'other/x.txt', b'x')
    await adapter.put(bucket, 'list/sub/deep.txt', b'deep')  # recursive: no delimiter

    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        page = await adapter.list(
            bucket, BlobListOptions(prefix='list/', limit=2, cursor=cursor)
        )
        pages += 1
        assert len(page.items) <= 2
        seen.extend(item.key for item in page.items)
        for item in page.items:
            assert item.bucket == bucket
            assert item.size > 0
        cursor = page.next_cursor
        if cursor is None:
            break
        assert pages < 10
    expected = sorted([*keys, 'list/sub/deep.txt'])
    assert seen == expected
    assert pages == 3

    everything = await adapter.list(bucket)
    assert [item.key for item in everything.items] == sorted([*expected, 'other/x.txt'])
    assert everything.next_cursor is None

    empty = await adapter.list(bucket, BlobListOptions(prefix='nothing-here/'))
    assert empty.items == []
    assert empty.next_cursor is None

    for limit in (0, 1001):
        try:
            await adapter.list(bucket, BlobListOptions(limit=limit))
            raise AssertionError(f'limit {limit} must raise BlobValidationError')
        except BlobValidationError:
            pass


async def check_copy(ctx: BlobSuiteContext) -> None:
    adapter, bucket = ctx.adapter, ctx.bucket
    await adapter.put(
        bucket,
        'copy/src.txt',
        b'payload',
        BlobPutOptions(content_type='text/plain', metadata={'k': 'v'}),
    )
    await adapter.copy(bucket, 'copy/src.txt', 'copy/dst.txt')
    target = await adapter.get(bucket, 'copy/dst.txt')
    assert target is not None
    assert target.body == b'payload'
    assert target.info.content_type == 'text/plain'
    assert target.info.metadata == {'k': 'v'}
    assert await adapter.exists(bucket, 'copy/src.txt') is True
    try:
        await adapter.copy(bucket, 'copy/missing.txt', 'copy/dst2.txt')
        raise AssertionError('copying a missing source must raise BlobNotFoundError')
    except BlobNotFoundError:
        pass
    assert await adapter.exists(bucket, 'copy/dst2.txt') is False


async def check_delete_and_delete_many(ctx: BlobSuiteContext) -> None:
    adapter, bucket = ctx.adapter, ctx.bucket
    await adapter.put(bucket, 'del/one.txt', b'1')
    await adapter.delete(bucket, 'del/one.txt')
    assert await adapter.exists(bucket, 'del/one.txt') is False
    await adapter.delete(bucket, 'del/one.txt')  # idempotent

    keys = [f'del/many-{i}.txt' for i in range(5)]
    for key in keys:
        await adapter.put(bucket, key, b'x')
    await adapter.delete_many(bucket, [*keys, 'del/never-existed.txt', keys[0]])
    page = await adapter.list(bucket, BlobListOptions(prefix='del/'))
    assert page.items == []
    await adapter.delete_many(bucket, [])
    await adapter.delete_many(bucket, keys)  # idempotent


async def check_validation(ctx: BlobSuiteContext) -> None:
    adapter, bucket = ctx.adapter, ctx.bucket
    bad_keys = [
        '',
        '/abs',
        'a//b',
        'a/./b',
        'a/../b',
        '..',
        'trailing/',
        'ctl\x00',
        'tab\tkey',
        'x' * 1025,
    ]
    for key in bad_keys:
        for call in (
            lambda k=key: adapter.put(bucket, k, b'x'),
            lambda k=key: adapter.get(bucket, k),
            lambda k=key: adapter.head(bucket, k),
            lambda k=key: adapter.delete(bucket, k),
            lambda k=key: adapter.presign(bucket, k),
        ):
            try:
                await call()
                raise AssertionError(f'key {key!r} must raise BlobValidationError')
            except BlobValidationError:
                pass
    for bad_bucket in (
        '',
        'ab',
        'UPPER',
        '-start',
        'end-',
        'has_underscore',
        'dou--ble',
        'x' * 64,
    ):
        try:
            await adapter.put(bad_bucket, 'k', b'x')
            raise AssertionError(
                f'bucket {bad_bucket!r} must raise BlobValidationError'
            )
        except BlobValidationError:
            pass
    for expires in (0, 604801):
        try:
            await adapter.presign(bucket, 'k', BlobPresignOptions(expires_in=expires))
            raise AssertionError(f'expires_in {expires} must raise BlobValidationError')
        except BlobValidationError:
            pass
    url = await adapter.presign(
        bucket, 'deep/key name.txt', BlobPresignOptions(expires_in=604800)
    )
    assert isinstance(url, str) and url


async def check_presigned_get(ctx: BlobSuiteContext) -> None:
    if ctx.http is None:
        raise BlobCheckSkipped('presigned URL checks need an HTTP client')
    adapter, bucket = ctx.adapter, ctx.bucket
    await adapter.put(
        bucket,
        'presign/get me.txt',
        b'download me',
        BlobPutOptions(content_type='text/plain'),
    )
    url = await adapter.presign(
        bucket, 'presign/get me.txt', BlobPresignOptions(expires_in=60)
    )
    response = await ctx.http('GET', url)
    assert response.status == 200, response.body
    assert response.body == b'download me'

    url = await adapter.presign(
        bucket, 'presign/get me.txt', BlobPresignOptions(download_name='report.txt')
    )
    response = await ctx.http('GET', url)
    assert response.status == 200, response.body
    assert (
        response.headers.get('content-disposition')
        == 'attachment; filename="report.txt"'
    )


async def check_presigned_put(ctx: BlobSuiteContext) -> None:
    if ctx.http is None:
        raise BlobCheckSkipped('presigned URL checks need an HTTP client')
    adapter, bucket = ctx.adapter, ctx.bucket
    url = await adapter.presign(
        bucket,
        'presign/uploaded.txt',
        BlobPresignOptions(method='PUT', content_type='text/plain', expires_in=60),
    )
    response = await ctx.http(
        'PUT', url, headers={'content-type': 'text/plain'}, content=b'uploaded body'
    )
    assert response.status in (200, 201), response.body
    obj = await adapter.get(bucket, 'presign/uploaded.txt')
    assert obj is not None
    assert obj.body == b'uploaded body'
    assert obj.info.content_type == 'text/plain'


async def check_missing_bucket(ctx: BlobSuiteContext) -> None:
    """put / get / list / copy raise `BlobNotFoundError`; head / exists → None / False; deletes are no-ops."""
    adapter = ctx.adapter
    missing = ctx.new_bucket_name()  # never created
    for name, call in (
        ('put', lambda: adapter.put(missing, 'k.txt', b'x')),
        ('get', lambda: adapter.get(missing, 'k.txt')),
        ('list', lambda: adapter.list(missing)),
        ('copy', lambda: adapter.copy(missing, 'a.txt', 'b.txt')),
    ):
        try:
            await call()
            raise AssertionError(
                f'{name} on a missing bucket must raise BlobNotFoundError'
            )
        except BlobNotFoundError:
            pass
    assert await adapter.head(missing, 'k.txt') is None
    assert await adapter.exists(missing, 'k.txt') is False
    await adapter.delete(missing, 'k.txt')
    await adapter.delete_many(missing, ['a.txt', 'b.txt'])
    assert await adapter.bucket_exists(missing) is False


BLOB_ADAPTER_CHECKS: dict[str, Callable[[BlobSuiteContext], Awaitable[None]]] = {
    'bucket_lifecycle': check_bucket_lifecycle,
    'put_get_head_exists': check_put_get_head_exists,
    'put_str_is_utf8': check_put_str_is_utf8,
    'overwrite': check_overwrite,
    'metadata_and_content_type': check_metadata_and_content_type,
    'missing_bucket': check_missing_bucket,
    'list_paging': check_list_paging,
    'copy': check_copy,
    'delete_and_delete_many': check_delete_and_delete_many,
    'validation': check_validation,
    'presigned_get': check_presigned_get,
    'presigned_put': check_presigned_put,
}
"""Every behaviour check, by name."""
