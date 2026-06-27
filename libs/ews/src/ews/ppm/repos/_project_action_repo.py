from db import BaseAsyncRepository

import db.models.ews as ews_models


class ProjectActionRepository(BaseAsyncRepository[ews_models.ProjectAction]):
    model_type = ews_models.ProjectAction
