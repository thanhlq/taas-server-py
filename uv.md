# uv guides

Tip:

- re-run uv whenever you add deps to a workspace member, or add the members to the root project's deps so plain uv sync works.

```bash
uv sync --all-packages
```

## uv command

```bash
# To add a python lib
uv init --lib libs/db

# To add an application
uv init --package packages/ews_api
```
