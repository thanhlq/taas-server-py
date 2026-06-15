# Running `banking_core` tests

## TL;DR

```bash
# From the repo root. Run the local-dev layer (fast, needs a local Postgres):
uv run pytest libs/banking_core/tests/unit_dev

# Run the CI layer (self-contained, needs Docker):
uv run pytest libs/banking_core/tests/unit

# Run everything:
uv run pytest libs/banking_core/tests
```

> ⚠️ **Never run a bare `uv sync` in this workspace.** Use `uv sync --all-packages`.
> See [Gotcha: a bare `uv sync` breaks the server](#gotcha-a-bare-uv-sync-breaks-the-server).

---

## Test layout

| Path                  | DB backend                  | When to use                          | Needs        |
| --------------------- | --------------------------- | ------------------------------------ | ------------ |
| `tests/conftest.py`   | — (shared fixtures)         | always loaded                        | —            |
| `tests/unit/`         | disposable **testcontainer**| CI / release / pre-push              | Docker       |
| `tests/unit_dev/`     | **local** database          | day-to-day development (inner loop)  | local Postgres |

Both layers run the *same* `CryptoTokenService` test suite — only the database
source differs. That source is the single `db_url` fixture each layer provides;
everything downstream (engine, schema, session, services, the token factory) is
defined once in `tests/conftest.py` and shared.

### Why two layers?

- **`unit` (testcontainer)** is hermetic and reproducible: it spins up a throw-away
  `postgres:16-alpine` container, so it works identically on any machine and in CI
  with zero local setup. The cost is ~20s of container startup and a Docker daemon.
- **`unit_dev` (local DB)** is the fast inner loop: it reuses your already-running
  local Postgres, so the whole suite finishes in well under a second and needs no
  Docker. The cost is that you must have a reachable database.

Keeping them as sibling folders (rather than a `--flag`) means each has its own
`conftest.py` providing `db_url`, and you simply point pytest at the folder you want.

---

## Prerequisites

### One-time: install the workspace (editable)

```bash
uv sync --all-packages
```

This installs **every** workspace member (the apps *and* the libs, including
`banking_core`) in editable mode. `banking_core` has no production dependents yet,
so only `--all-packages` puts it on the Python path.

### For `unit_dev`: a local database

`unit_dev` reads `DATABASE_URL` from `.env.test` (loaded automatically by
`tests/conftest.py`). The default points at:

```
postgresql+psycopg_async://postgres:Pa55w0rd@localhost:5432/taas_next_test
```

Make sure that database is reachable. The suite creates only the **banking**
tables it needs and truncates only those tables between tests, so it will not
touch unrelated data in that database.

If `DATABASE_URL` is unset the `unit_dev` layer **skips**; if it is set to a
non-async driver it **fails fast** with a clear message.

### For `unit`: Docker

The `unit` layer needs a running Docker daemon (Docker Desktop, Colima, etc.).
Nothing else — the container is created and destroyed by the test session.

---

## How isolation works

- The engine and schema are created **once per session** (`db_engine`,
  session-scoped) using a `NullPool`, so the session-scoped engine is safe to use
  from function-scoped async tests (no event-loop binding issues).
- Each test gets a **fresh `AsyncSession`** (`db_session`, function-scoped).
- After each test, the banking tables are `TRUNCATE ... RESTART IDENTITY CASCADE`d,
  so tests never leak state into one another (see `test_isolation_between_tests`).

`pytest-asyncio` runs in `asyncio_mode = "auto"` (configured in
`libs/banking_core/pyproject.toml`), so async tests and fixtures need no explicit
`@pytest.mark.asyncio` marker.

---

## The token factory

Shared fixtures expose a `token_factory` (the `CryptoTokenFactory` class) for
building `CryptoToken` create-payloads with sensible presets:

```python
async def test_example(crypto_token_service, token_factory):
    btc = token_factory.btc()                       # preset
    eth = token_factory.eth(network="sepolia")      # preset + overrides
    kas = token_factory.build("KAS")                # generic build by symbol

    created = await crypto_token_service.create_crypto_token(btc)
    assert created.symbol == "BTC"
```

Built-in presets: **BTC, ETH, SOL, KAS**. `token_factory.all_presets()` returns
one payload per preset (handy for seeding). Any field can be overridden with a
keyword argument.

---

## Common commands

```bash
# A single test file
uv run pytest libs/banking_core/tests/unit_dev/test_crypto_token_service.py

# A single test, verbose
uv run pytest libs/banking_core/tests/unit_dev/test_crypto_token_service.py::test_create_crypto_token -v

# Stop on first failure, show prints
uv run pytest libs/banking_core/tests/unit_dev -x -s
```

---

## Gotcha: a bare `uv sync` breaks the server

**Symptom:** the start scripts suddenly fail with:

```
/.../.venv/bin/python3: No module named ews_api
```

(and the same for `ews_api_litestar`, `http_fastapi`, etc.)

**Cause:** the root project sets `package = false` and the apps are only reachable
as workspace members — not as dependencies of the root. A plain `uv sync` installs
only the root project's dependency closure and **removes** every workspace member
that isn't in it (the editable `.pth` files for `ews_api`, `http_fastapi`, … get
deleted).

**Fix / always use:**

```bash
uv sync --all-packages
```

This reinstalls all members editable and restores the `.pth` files, after which
`./start_ews_api_fastapi.sh` and `./start_ews_api_litestar.sh` work again.

You can verify the environment is complete with:

```bash
uv run python -c "import ews_api, ews_api_litestar, banking_core; print('ok')"
```
