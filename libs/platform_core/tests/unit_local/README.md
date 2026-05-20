# Local Unit Test

Containing tests running in local only

## Execute tests

From the repo root:

```bash
uv run --package platform_core pytest -v libs/platform_core/tests/unit_local
```

Or from this package:

```bash
cd libs/platform_core && uv run pytest -v tests/unit_local
```
