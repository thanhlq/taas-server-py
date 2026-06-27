from db import BaseAsyncRepository

import db.models.ews as ews_models


class ProjectRiskRepository(BaseAsyncRepository[ews_models.ProjectRisk]):
    model_type = ews_models.ProjectRisk
