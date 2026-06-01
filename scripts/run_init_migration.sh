#!/bin/bash

# Run init migration for local development
# You must stable in the root directory of the project to run this script
# scripts/run_init_migration.sh

echo "Current dir: $(pwd)"
echo "MAKE SURE, to clean: libs/db/src/db/migrations/versions before running this script"
echo "MAKE SURE, to delete database tables before running this script"

uv run python -m db.migrations revision --autogenerate -m "init database"
uv run python -m db.migrations upgrade
