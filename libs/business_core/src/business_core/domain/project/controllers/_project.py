import re
from typing import Any
import msgspec
from fastapi import Response
from business_core.domain.project.schemas import Project

from platform_core.utils.datetime_utils import now_in_utc

samples_project: list[Project] = [
    Project(id=1, name="Sample Project", created_at=now_in_utc()),
    Project(id=2, name="Another Project", created_at=now_in_utc())
]

class MsgspecResponse(Response):
    """JSON response using the msgspec library to serialize data to JSON.

    **Deprecated**: `MsgspecResponse` is deprecated. FastAPI now serializes data
    directly to JSON bytes via Pydantic when a return type or response model is
    set, which is faster and doesn't need a custom response class.

    Read more in the
    [FastAPI docs for Custom Response](https://fastapi.tiangolo.com/advanced/custom-response/#orjson-or-response-model)
    and the
    [FastAPI docs for Response Model](https://fastapi.tiangolo.com/tutorial/response-model/).

    **Note**: `msgspec` is not included with FastAPI and must be installed
    separately, e.g. `pip install msgspec`.
    """

    def render(self, content: Any) -> bytes:
        return msgspec.json.encode(content)



class ProjectController:
    api_prefix = "/api/v1/projects"

    def __init__(self, router):
        self.router = router
        self._register_routes()

    def _register_routes(self):
        @self.router.get(path="/")
        def list_projects() -> list[Project]:
            # Implement your logic to list projects here
            # return [{"id": 1, "name": "Sample Project"}, {"id": 2, "name": "Another Project"}]
            return samples_project

        def get_project(self, project_id: int) -> dict:
            # Implement your logic to retrieve a project by ID here
            return {"id": project_id, "name": "Sample Project"}

        def update_project(self, project_id: int, name: str) -> dict:
            # Implement your logic to update a project here
            return {"id": project_id, "name": name}

        def delete_project(self, project_id: int) -> None:
            # Implement your logic to delete a project here
            pass