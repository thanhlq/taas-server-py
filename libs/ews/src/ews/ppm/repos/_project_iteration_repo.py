from db import BaseAsyncRepository

import db.models.ews as ews_models


class ProjectIterationRepository(BaseAsyncRepository[ews_models.ProjectIteration]):
    model_type = ews_models.ProjectIteration
