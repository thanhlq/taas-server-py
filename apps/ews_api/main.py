from fastapi_msgspec.responses import MsgSpecJSONResponse
from fastapi_msgspec.routing import MsgSpecRoute

# uv run --prerelease=allow python -m ews_api.main
# uv run --package ews_api python main.py

from business_core.domain.project import ProjectController
from fastapi import APIRouter
from rest_fastapi.base_fastapi_app import build_app
from rest_fastapi.uvicorn import run_uvicorn



app = build_app(default_response_class=MsgSpecJSONResponse)

# app.router.route_class = MsgSpecRoute

def main():
    print("Hello from ews-api!")

    router = APIRouter(prefix=ProjectController.api_prefix, tags=['Project API'],
                       route_class=MsgSpecRoute)

    ProjectController(router)

    app.include_router(router)

    run_uvicorn(app)


if __name__ == "__main__":
    main()
