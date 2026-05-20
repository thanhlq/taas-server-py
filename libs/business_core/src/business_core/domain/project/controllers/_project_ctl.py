from business_core.domain.project.schemas import Project
from business_core.domain.project.schemas._project import ProjectEntityPy
from rest_fastapi.fastapi_msgspec.openapi import msgspec_response
from rest_fastapi.fastapi_msgspec.responses import MsgSpecJSONResponse

from platform_core.utils.datetime_utils import now_in_utc

samples_project: list[Project] = [
    Project(id=1, name="Sample Project", created_at=now_in_utc()),
    Project(id=2, name="Another Project", created_at=now_in_utc())
]

samples_project2: list[ProjectEntityPy] = [
    ProjectEntityPy(id=1, name="Sample Project", created_at=now_in_utc()),
    ProjectEntityPy(id=2, name="Another Project", created_at=now_in_utc())
]


class ProjectController:
    api_prefix = "/api/v1/projects"

    def __init__(self, router):
        self.router = router
        self._register_routes()

    def _register_routes(self):
        @self.router.get(
            path="/",
        )
        def list_projects() -> list[Project]:
            return samples_project

        @self.router.get(
            path="/p1",
            response_model=None,
            openapi_extra=msgspec_response(list[Project]),
        )
        def list_projects1() -> MsgSpecJSONResponse:
            return MsgSpecJSONResponse(samples_project)

        @self.router.get(
            path="/p2",
        )
        def list_projects2() -> list[ProjectEntityPy]:
            return samples_project2

        # def get_project(self, project_id: int) -> dict:
        #     # Implement your logic to retrieve a project by ID here
        #     return {"id": project_id, "name": "Sample Project"}

        # def update_project(self, project_id: int, name: str) -> dict:
        #     # Implement your logic to update a project here
        #     return {"id": project_id, "name": name}

        # def delete_project(self, project_id: int) -> None:
        #     # Implement your logic to delete a project here
        #     pass