from ews.domain.project.schemas import Project

from platform_core.utils.datetime_utils import now_in_utc

samples_project: list[Project] = [
    Project(id=1, name="Sample Project", created_at=now_in_utc()),
    Project(id=2, name="Another Project", created_at=now_in_utc())
]


class ProjectController:
    api_prefix = "/api/v1/projects"

    def __init__(self, router):
        self.router = router
        self._register_routes()

    def _register_routes(self):
        @self.router.get(path="/")
        def list_projects() -> list[Project]:
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