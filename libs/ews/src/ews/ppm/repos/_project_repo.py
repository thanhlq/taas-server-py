from db import BaseAsyncRepository

import db.models.ews as ews_models


class ProjectRepository(BaseAsyncRepository[ews_models.Project]):
    model_type = ews_models.Project
