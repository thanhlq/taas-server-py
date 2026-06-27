from db import BaseAsyncRepository

import db.models.ews as ews_models


class WorkflowStageRepository(BaseAsyncRepository[ews_models.WorkflowStage]):
    model_type = ews_models.WorkflowStage
