"""Signed delivery of the File Manager (taas-specs/files File-0500 … File-0505, ADR-9 / ADR-10): URL lifetime per
drive sensitivity, rounded expiries, the signed-URL cache, HTTP headers, byte ranges."""

from __future__ import annotations

import pytest

from ews.files._delivery import (
    UrlPolicy,
    content_headers,
    epoch_of,
    etag_of,
    parse_range,
    sensitivity_of,
    url_policy,
)
from ews.files._settings import FilesSettings
from ews.shared import SignedUrlCache, rounded_expiry

SETTINGS = FilesSettings(url_ttl_seconds=300, view_ttl_seconds=86400)


def test_file_0500_url_lifetime_follows_the_drive_sensitivity():
    standard, confidential = {}, {'sensitivity': 'confidential'}
    assert url_policy(standard, view=True, settings=SETTINGS) == UrlPolicy(86400, True)
    assert url_policy(standard, view=False, settings=SETTINGS) == UrlPolicy(
        300, False
    )  # downloads stay short
    assert url_policy(confidential, view=True, settings=SETTINGS) == UrlPolicy(
        300, False
    )
    assert (
        sensitivity_of(None) == 'standard'
        and sensitivity_of({'sensitivity': 'x'}) == 'standard'
    )
    assert (
        epoch_of({'url_epoch': 3}) == 3
        and epoch_of({'url_epoch': 'bad'}) == 0
        and epoch_of(None) == 0
    )


def test_file_0501_expiries_are_rounded_so_urls_repeat():
    ttl = 86400
    step = ttl // 4
    base = 1_800_000_000 - 1_800_000_000 % step
    first = rounded_expiry(ttl, base + 10)
    assert first == rounded_expiry(ttl, base + step - 1)  # same window → same expiry
    assert rounded_expiry(ttl, base + step) == first + step  # next window
    for now in (base, base + 1, base + step - 1):
        assert (
            ttl - step < rounded_expiry(ttl, now) - now <= ttl
        )  # never longer than the policy


async def test_file_0501_signed_urls_are_signed_once_per_window():
    cache = SignedUrlCache('test', max_entries=2, margin=60)
    calls: list[str] = []

    async def sign() -> str:
        calls.append('x')
        return f'https://signed/{len(calls)}'

    now = 1_000_000.0
    assert (
        await cache.get_or_sign('k1', int(now) + 3600, sign, now=now)
        == 'https://signed/1'
    )
    assert (
        await cache.get_or_sign('k1', int(now) + 3600, sign, now=now + 5)
        == 'https://signed/1'
    )
    assert len(calls) == 1
    assert (
        await cache.get_or_sign('k1', int(now) + 7200, sign, now=now)
        == 'https://signed/2'
    )  # new window
    assert (
        await cache.get_or_sign('k1', int(now) + 30, sign, now=now)
        == 'https://signed/3'
    )  # too short: no cache
    await cache.get_or_sign('k2', int(now) + 3600, sign, now=now)
    assert len(cache) == 2  # bounded (oldest evicted)
    cache.clear()
    assert len(cache) == 0


def test_file_0502_headers_cache_views_and_never_downloads():
    view = content_headers(
        'image/webp',
        'thumbnail.webp',
        inline=True,
        cacheable=True,
        exp=1_000_600,
        etag='abc',
        now=1_000_000,
    )
    assert view['cache-control'] == 'private, max-age=600, immutable'
    assert view['etag'] == '"abc"' and view['x-content-type-options'] == 'nosniff'
    assert (
        'sandbox' in view['content-security-policy']
        and view['accept-ranges'] == 'bytes'
    )
    download = content_headers(
        'application/zip', 'a.zip', inline=False, exp=1_000_600, now=1_000_000
    )
    assert download['cache-control'] == 'private, no-store'
    assert download['content-disposition'].startswith('attachment;')
    assert 'content-security-policy' not in content_headers(
        'application/pdf', 'a.pdf', inline=True
    )
    assert etag_of('documents/x') == etag_of('documents/x') != etag_of('documents/y')


@pytest.mark.parametrize(
    ('header', 'expected'),
    [
        (None, None),
        ('bytes=0-99', (0, 99)),
        ('bytes=900-', (900, 999)),
        ('bytes=-100', (900, 999)),
        ('bytes=950-5000', (950, 999)),
        ('bytes=1000-', False),
        ('bytes=5-1', False),
        ('bytes=0-1,5-6', None),
        ('items=0-1', None),
        ('bytes=a-b', None),
    ],
)
def test_file_0502_single_byte_ranges(header: str | None, expected):
    assert parse_range(header, 1000) == expected
