# uv run --package ews-api python main.py
uv sync
uv run --package ews_api_litestar python -m ews_api_litestar.main
