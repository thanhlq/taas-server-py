from db import BaseAsyncRepository

import db.models.ews as ews_models


class ProjectTeamRepository(BaseAsyncRepository[ews_models.ProjectTeam]):
    model_type = ews_models.ProjectTeam
