from db import BaseAsyncRepository

import db.models.ews as ews_models


class WorkflowRepository(BaseAsyncRepository[ews_models.Workflow]):
    model_type = ews_models.Workflow
