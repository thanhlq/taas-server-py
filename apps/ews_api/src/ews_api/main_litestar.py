# uv run --prerelease=allow python -m ews_api.main_litestar
#
# Litestar variant of the ews_api server. The route definitions live in
# ``ews`` and are framework-agnostic; this entry point wires them into a
# Litestar app via ``http_litestar.adapters``.
from litestar import Litestar

from ews.domain.project import ProjectController
from http_litestar.adapters import build_router_for_controller
from http_litestar.base_litestar_app import build_app
from http_litestar.uvicorn import run_uvicorn

from .setup_env import setup_environment

settings = setup_environment()

app: Litestar = build_app(
    route_handlers=[build_router_for_controller(ProjectController())],
)


def main() -> None:
    print('Hello from ews-api (litestar)!')
    run_uvicorn(app)


if __name__ == '__main__':
    main()
