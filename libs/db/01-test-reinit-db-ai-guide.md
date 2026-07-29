# AI Task - Reinitialize database migration

help me to reinit the database migration (from begining)
0. Remove all existing in taas-server-py/libs/db/src/db/migrations/versions
1. uv run python -m db.migrations revision --autogenerate -m "init database"
2. uv run python -m db.migrations upgrade
3. and then must fix the generated revision from sample working in libs/db/src/db/migrations/ref/2026-07-11_init_database_b28a9ffadaab.py regarding to creating of enums (one time only to fix duplicated) and wrong jsontext import
