# taas-server-py

Python `uv` workspace for the EWS API (FastAPI/Litestar), workers, messaging, IAM, storage and shared foundations.

## Environment files

Create a local runtime file from the documented template:

```bash
cp .env.example .env
```

`.env.example` documents the supported settings, defaults, allowed values and local infra defaults
(`docker-compose.infra.yml`: Redis cache `localhost:16379`, Redis store `localhost:16380`,
Mailpit SMTP `localhost:1025`, RustFS S3 `localhost:19000`). Real `.env` and `.env.test` files
are gitignored and must hold secrets only locally or in a secret manager.

The loader reads `ENV_FILE` when set, otherwise `.env`, using `python-dotenv`; process environment
variables win. It does **not** automatically layer `.env.local`, so use `.env` for normal local
overrides or set `ENV_FILE=<file>` deliberately.

Test defaults live in `.env.test.example`; copy it only when you need a local `.env.test`:

```bash
cp .env.test.example .env.test
```

Check template/runtime key sync with:

```bash
python3 ../taas-tools/env-check/check_env.py taas-server-py
```