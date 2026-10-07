"""Storage resolver (pooled / dedicated, kinds) and the public CDN store (taas-specs/platform/storage)."""

from __future__ import annotations

import hashlib
import uuid

import pytest
from blob_service import (
    AdapterPublicStore,
    DefaultBlobService,
    DisabledPublicStore,
    MemoryBlobAdapter,
    MemoryTenantBucketRegistry,
    create_public_store,
    create_storage_resolver,
)
from foundation.blob import (
    BlobListOptions,
    BlobValidationError,
    CdnSettings,
    StorageSettings,
    kind_key,
)

POOLED = 'taas-private-test'


def _setup(**tenants: str | None):
    adapter = MemoryBlobAdapter()
    registry = MemoryTenantBucketRegistry()
    ids = {}
    for name, mode in tenants.items():
        ids[name] = str(uuid.uuid4())
        registry.add_tenant(ids[name], f'{len(ids):08d}', storage_mode=mode)
    blob = DefaultBlobService(adapter, registry, bucket_prefix='taas-')
    resolver = create_storage_resolver(
        blob, registry, StorageSettings(STORAGE_PRIVATE_MODE='pooled', STORAGE_PRIVATE_BUCKET=POOLED), register=False
    )
    return adapter, registry, resolver, ids


async def test_pooled_tenants_share_one_bucket_under_their_prefix():
    adapter, _, resolver, ids = _setup(a=None, b=None)
    loc = await resolver.resolve(ids['a'], 'upload')
    assert (loc.bucket, loc.prefix, loc.mode) == (POOLED, f'{ids["a"]}/uploads/', 'pooled')
    a = await resolver.store(ids['a'], 'document')
    b = await resolver.store(ids['b'], 'document')
    await a.put('x.txt', b'a')
    await b.put('x.txt', b'b')
    assert (await a.get('x.txt')).body == b'a'
    assert (await b.get('x.txt')).body == b'b'
    assert [i.key for i in (await a.list()).items] == ['x.txt']
    raw = await adapter.list(POOLED, BlobListOptions())
    assert sorted(i.key for i in raw.items) == sorted([f'{ids["a"]}/documents/x.txt', f'{ids["b"]}/documents/x.txt'])


async def test_dedicated_tenants_get_their_own_bucket():
    adapter, _, resolver, ids = _setup(ent='dedicated')
    loc = await resolver.resolve(ids['ent'], 'knowledge')
    assert loc.mode == 'dedicated' and loc.bucket == 'taas-00000001' and loc.prefix == 'knowledge/'
    root = await resolver.root(ids['ent'])
    await root.put(kind_key('upload', 'media/o.png'), b'png')
    assert await adapter.exists('taas-00000001', 'uploads/media/o.png')


async def test_a_stored_bucket_means_dedicated_and_is_recreated_when_missing():
    adapter = MemoryBlobAdapter()
    registry = MemoryTenantBucketRegistry()
    tid = str(uuid.uuid4())
    registry.add_tenant(tid, '00000009', bucket='legacy-bucket')  # e.g. provisioned on another provider
    blob = DefaultBlobService(adapter, registry)
    resolver = create_storage_resolver(blob, registry, StorageSettings(), register=False)
    assert (await resolver.resolve(tid, 'upload')).bucket == 'legacy-bucket'
    assert await adapter.bucket_exists('legacy-bucket')


async def test_prefixed_store_rejects_absolute_keys_and_pages_relatively():
    _, _, resolver, ids = _setup(a=None)
    store = await resolver.store(ids['a'], 'derived')
    with pytest.raises(BlobValidationError):
        await store.put('/abs', b'x')
    for i in range(5):
        await store.put(f'k{i}', b'x')
    first = await store.list(BlobListOptions(limit=2))
    assert [i.key for i in first.items] == ['k0', 'k1'] and first.next_cursor == 'k1'
    second = await store.list(BlobListOptions(limit=10, cursor=first.next_cursor))
    assert [i.key for i in second.items] == ['k2', 'k3', 'k4']


async def test_public_store_writes_content_hashed_immutable_objects_once():
    adapter = MemoryBlobAdapter()
    await adapter.ensure_bucket('cdn-test')
    store = AdapterPublicStore(adapter, 'cdn-test', 'https://cdn.example/')
    tenant = str(uuid.uuid4())
    calls = 0

    async def load() -> bytes:
        nonlocal calls
        calls += 1
        return b'image'

    first = await store.publish(tenant, 'site/s1', ext='webp', content_type='image/webp', load=load)
    digest = hashlib.sha256(b'image').hexdigest()
    assert first.created and first.key == f'{tenant}/site/s1/{digest}.webp'
    assert first.url == f'https://cdn.example/{tenant}/site/s1/{digest}.webp'
    info = await adapter.head('cdn-test', first.key)
    assert info is not None and info.content_type == 'image/webp'
    again = await store.publish(tenant, 'site/s1', ext='webp', content_type='image/webp', load=load, sha256=digest)
    assert not again.created and calls == 1  # known hash + existing object: not re-read
    with pytest.raises(BlobValidationError):
        await store.publish(tenant, 'site/s1', ext='webp', content_type='image/webp', load=load, sha256='0' * 64)


async def test_public_store_deletes_a_scope_and_a_tenant():
    adapter = MemoryBlobAdapter()
    await adapter.ensure_bucket('cdn-test')
    store = AdapterPublicStore(adapter, 'cdn-test', 'https://cdn.example')
    t1, t2 = str(uuid.uuid4()), str(uuid.uuid4())
    for tenant, scope, body in ((t1, 'site/a', b'1'), (t1, 'site/a', b'2'), (t1, 'blog/b', b'3'), (t2, 'site/a', b'4')):
        await store.publish(tenant, scope, ext='png', content_type='image/png', load=lambda b=body: _value(b))
    assert await store.delete_scope(t1, 'site/a') == 2
    assert await store.delete_tenant(t1) == 1
    remaining = await adapter.list('cdn-test', BlobListOptions())
    assert [i.key.split('/')[0] for i in remaining.items] == [t2]
    with pytest.raises(BlobValidationError):
        await store.delete_scope(t1, '../x')


async def _value(body: bytes) -> bytes:
    return body


def test_create_public_store_is_disabled_without_a_cdn():
    assert isinstance(create_public_store(CdnSettings(CDN_SERVICE_PROVIDER='', CDN_BUCKET_NAME='', CDN_BUCKET_PUBLIC_URL=''), register=False), DisabledPublicStore)
    settings = CdnSettings(
        CDN_SERVICE_PROVIDER='cloudflare', CDN_BUCKET_NAME='cdn-eu', CDN_BUCKET_PUBLIC_URL='https://cdn.example/',
        CDN_BUCKET_SERVICE_URL='https://acc.eu.r2.cloudflarestorage.com',
    )
    store = create_public_store(settings, MemoryBlobAdapter(), register=False)
    assert store.enabled and store.base_url == 'https://cdn.example'
    with pytest.raises(BlobValidationError):
        StorageSettings(STORAGE_PRIVATE_MODE='shared')
