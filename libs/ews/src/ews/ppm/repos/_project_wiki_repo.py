from db import BaseAsyncRepository
from db.models.ews._project_post import ProjectWiki


class ProjectWikiRepository(BaseAsyncRepository[ProjectWiki]):
    model_type = ProjectWiki
