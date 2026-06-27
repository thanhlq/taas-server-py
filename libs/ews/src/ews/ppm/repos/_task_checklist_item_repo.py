from db import BaseAsyncRepository

import db.models.ews as ews_models


class TaskChecklistItemRepository(BaseAsyncRepository[ews_models.TaskChecklistItem]):
    model_type = ews_models.TaskChecklistItem
