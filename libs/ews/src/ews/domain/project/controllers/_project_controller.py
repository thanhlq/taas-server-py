from ews.domain.project.schemas import Project
from ews.domain.project.schemas._project import ProjectEntityPy
from platform_core.http import BaseController, get
from platform_core.utils.datetime_utils import now_in_utc

samples_project: list[Project] = [
    Project(id=1, name='Sample Project', created_at=now_in_utc()),
    Project(id=2, name='Another Project', created_at=now_in_utc()),
]

samples_project2: list[ProjectEntityPy] = [
    ProjectEntityPy(id=1, name='Sample Project', created_at=now_in_utc()),
    ProjectEntityPy(id=2, name='Another Project', created_at=now_in_utc()),
]


class ProjectController(BaseController):
    api_prefix = '/api/v1/projects'
    tags = ('Project API',)

    @get('/')
    def list_projects(self) -> list[Project]:
        return samples_project

    @get('/p2')
    def list_projects2(self) -> list[ProjectEntityPy]:
        return samples_project2
