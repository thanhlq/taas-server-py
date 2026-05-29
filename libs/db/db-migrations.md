# DB Migrations

## Alembic

### Create 1st migration

```bash
uv run alembic -c db/src/db/migrations/alembic.ini revision --autogenerate -m "Create users table"
```
