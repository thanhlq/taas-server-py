from db import BaseAsyncRepository

import db.models.ews as ews_models


class TaskRepository(BaseAsyncRepository[ews_models.Task]):
    model_type = ews_models.Task
