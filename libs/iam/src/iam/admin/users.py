# SHOULD INLUCDE IN local dev/test

from typing import TYPE_CHECKING

from ews.ppm.schemas import Project
from foundation.http import (
    BaseController,
    get,
)

if TYPE_CHECKING:
    pass

class ProjectController(BaseController):
    api_prefix = '/api/v1/projects'
    tags = ('Project API',)

    @get('/', ratelimit='3/minute')
    def list_projects(self) -> list[Project]:
        return samples_project
