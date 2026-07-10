# Local Unit Test

Containing tests running in local only

## Execute tests

From the repo root:

```bash
uv run --package foundation pytest -v libs/foundation/tests/unit_local

# single file
uv run --package foundation pytest -v libs/foundation/tests/unit_local/test_async_cache_ttl_ignore_all_arg.py
```

Or from this package:

```bash
cd libs/foundation && uv run pytest -v tests/unit_local
```
