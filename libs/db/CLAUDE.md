# Project

## Folder structure

- tests/unit: contain official unit tests / executed in releases
- tests/unit_dev: contain unit tests that executed during development only (local machine)

## Run migration

see libs/db/src/db/migrations/migration-guide.md

Rules when generating migration (first time)

1. uv run python -m db.migrations revision --autogenerate -m "init database"
2. uv run python -m db.migrations upgrade
3. and then must fix the generated revision from sample working in libs/db/src/db/migrations/ref/2026-07-11_init_database_b28a9ffadaab.py regarding to creating of enums (one time only to fix duplicated) and wrong jsontext import
