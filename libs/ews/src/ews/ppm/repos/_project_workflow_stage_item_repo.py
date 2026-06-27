from db import BaseAsyncRepository

import db.models.ews as ews_models


class ProjectWorkflowStageItemRepository(BaseAsyncRepository[ews_models.ProjectWorkflowStageItem]):
    model_type = ews_models.ProjectWorkflowStageItem
