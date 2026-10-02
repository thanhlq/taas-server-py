"""``uv run python -m resiliant.migrations upgrade|status|drop`` against ``DATABASE_URL``.

``drop`` refuses non-local hosts and ``ENVIRONMENT=production``.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from .runner import (
    applied_migrations,
    drop_resiliant_tables,
    read_migrations,
    run_resiliant_migrations,
)


def _url() -> str:
    from foundation.config import get_settings

    url = make_url(os.environ.get('DATABASE_URL') or get_settings().db.URL)
    if url.drivername == 'postgresql':
        url = url.set(drivername='postgresql+psycopg')
    return url.render_as_string(hide_password=False)


async def _main(command: str) -> int:
    url = _url()
    engine = create_async_engine(url)
    try:
        if command == 'upgrade':
            applied = await run_resiliant_migrations(engine)
            print(
                f'resiliant migrations: {", ".join(applied) if applied else "up to date"}'
            )
        elif command == 'status':
            known = {m.hash: m.tag for m in read_migrations()}
            for hash_, created_at in await applied_migrations(engine):
                print(f'{known.get(hash_, "?unknown?")}\t{created_at}\t{hash_[:12]}')
        elif command == 'drop':
            host = make_url(url).host or ''
            if os.environ.get('ENVIRONMENT') == 'production' or host not in {
                'localhost',
                '127.0.0.1',
                'db',
                'postgres',
            }:
                print(
                    f'refusing to drop resiliant tables on host {host!r}',
                    file=sys.stderr,
                )
                return 1
            await drop_resiliant_tables(engine)
            print('resiliant tables dropped')
        return 0
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='python -m resiliant.migrations')
    parser.add_argument('command', choices=['upgrade', 'status', 'drop'])
    return asyncio.run(_main(parser.parse_args(argv).command))


if __name__ == '__main__':
    sys.exit(main())
