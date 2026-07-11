# resiliant/tests

```bash
# should define .env.test in the root

uv sync --all-packages
uv run --package resiliant pytest libs/resiliant/tests/unit
```
