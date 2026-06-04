# DB Migrations

Migrations live in `libs/db/src/db/migrations/`. The runner is invoked via the
package's `__main__`, so any CWD works as long as the `db` package is importable.

## Quick reference

```bash
# Read-only
uv run python -m db.migrations current        # show DB's current revision
uv run python -m db.migrations history        # full revision history

# Create revisions
uv run python -m db.migrations revision --autogenerate -m "init database"
uv run python -m db.migrations revision -m "manual fix" # empty template

# Apply / roll back
uv run python -m db.migrations upgrade head
uv run python -m db.migrations upgrade +1
uv run python -m db.migrations downgrade -1
# Reset to beginning -> clear all tables
uv run python -m db.migrations downgrade base

# Inspect SQL without running it
uv run python -m db.migrations upgrade head --sql > migration.sql

# Mark DB at a revision without running it (e.g. after manual SQL)
uv run python -m db.migrations stamp head
```

## How it's wired

- **Config source**: `Settings.db.URL` (from `platform_core.config.get_settings`),
  read from `taas-server-py/.env` via `DATABASE_URL`.
- **Version table**: `Settings.db.MIGRATION_DDL_VERSION_TABLE` (default `ddl_version`).
- **Models**: `db.models.__init__` is imported in `env.py`, so any class
  registered with `advanced_alchemy.base.UUIDv7AuditBase` (or other AA bases) is
  picked up by `--autogenerate` automatically. Add new models there.
- **Driver**: URLs with bare `postgresql://` are normalised to
  `postgresql+psycopg://` (psycopg3 supports both sync and async with the same
  dialect name).

## Adding a new revision after a model change

1. Edit / add a model in `libs/db/src/db/models/` (and re-export from
   `db/models/__init__.py`).
2. Run autogenerate:

   ```bash
   uv run python -m db.migrations revision --autogenerate -m "add foo column"
   ```

3. **Inspect the generated file** in `libs/db/src/db/migrations/versions/` —
   autogenerate is not always right (renames look like drop+add, server
   defaults may need manual tweaking, data migrations must be hand-written).
4. Apply:

   ```bash
   uv run python -m db.migrations upgrade head
   ```

5. Commit the new revision file alongside the model change.

## Docker (one-shot)

Run migrations as a separate one-shot before starting the API. Example with
`docker compose`:

```yaml
# docker-compose.yml (snippet)
services:
  migrate:
    image: taas-server-py:latest    # same image as the API
    command: >
      uv run --prerelease=allow python -m db.migrations upgrade head
    environment:
      DATABASE_URL: ${DATABASE_URL}
    depends_on:
      postgres:
        condition: service_healthy
    restart: "no"

  api:
    image: taas-server-py:latest
    depends_on:
      migrate:
        condition: service_completed_successfully
    # ...
```

Then:

```bash
docker compose run --rm migrate                          # apply migrations
docker compose run --rm migrate \
  uv run python -m db.migrations current                  # inspect current rev
docker compose run --rm migrate \
  uv run python -m db.migrations revision --autogenerate -m "..."   # generate (writes into the mounted volume only if you bind-mount libs/db/)
```

For revision generation in docker, bind-mount the source so the new file
persists on the host:

```bash
docker compose run --rm \
  -v "$PWD/libs/db/src/db/migrations:/app/libs/db/src/db/migrations" \
  migrate uv run python -m db.migrations revision --autogenerate -m "new change"
```

## Troubleshooting

- **`No module named 'psycopg'`** — run `uv sync --prerelease=allow`. The
  driver is declared in `libs/db/pyproject.toml`.
- **`AttributeError: 'Config' object has no attribute 'db_url'`** — you ran
  plain `alembic` against `env.py`. Use `python -m db.migrations` instead;
  `env.py` is written for advanced-alchemy's `AlembicCommandConfig`.
- **Autogenerate produces an empty migration when you expect changes** —
  the new model isn't reachable from `db.models`. Make sure it's imported (and
  optionally re-exported) from `libs/db/src/db/models/__init__.py` — `env.py`
  imports that package to populate `metadata_registry`.
- **`Error getting version: No package metadata was found for litestar`** —
  cosmetic; comes from `platform_core/utils/version.py` falling back to
  `'litestar'` when `APP_MODULE_NAME` isn't set. Doesn't affect migrations.
