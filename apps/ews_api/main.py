# uv run --prerelease=allow python -m ews_api.main
# uv run --package ews_api python main.py

from framework_fastapi.base_fastapi_app import build_app
from framework_fastapi.uvicorn import run_uvicorn


app = build_app()


def main():
    print("Hello from ews-api!")

    run_uvicorn(app)


if __name__ == "__main__":
    main()
