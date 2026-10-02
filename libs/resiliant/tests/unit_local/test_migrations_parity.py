"""The vendored drizzle migrations must be byte-identical to taas-server-js (one DDL source)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from resiliant.migrations import RESILIANT_MIGRATIONS_FOLDER, read_migrations

JS_FOLDER = (
    Path(__file__).resolve().parents[5]
    / 'taas-server-js'
    / 'packages'
    / 'resiliant'
    / 'drizzle'
)


def _files(folder: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(folder)): p.read_bytes()
        for p in sorted(folder.rglob('*'))
        if p.is_file()
    }


@pytest.mark.skipif(
    not JS_FOLDER.exists(),
    reason='taas-server-js is not checked out next to taas-server-py',
)
def test_vendored_migrations_match_taas_server_js() -> None:
    assert _files(RESILIANT_MIGRATIONS_FOLDER) == _files(JS_FOLDER), (
        'resiliant migrations drifted: run scripts/sync-resiliant-migrations.sh'
    )


def test_migrations_hash_like_drizzle() -> None:
    migrations = read_migrations()
    assert migrations and migrations[0].tag == '0000_init'
    for migration in migrations:
        raw = (RESILIANT_MIGRATIONS_FOLDER / f'{migration.tag}.sql').read_bytes()
        assert migration.hash == hashlib.sha256(raw).hexdigest()
        assert ''.join(migration.statements) == raw.decode().replace(
            '--> statement-breakpoint', ''
        )
