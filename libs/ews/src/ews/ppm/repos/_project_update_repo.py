from db import BaseAsyncRepository

import db.models.ews as ews_models


class ProjectUpdateRepository(BaseAsyncRepository[ews_models.ProjectUpdate]):
    model_type = ews_models.ProjectUpdate
