from db import BaseAsyncRepository

import db.models.ews as ews_models


class ProjectUserRepository(BaseAsyncRepository[ews_models.ProjectUser]):
    model_type = ews_models.ProjectUser
