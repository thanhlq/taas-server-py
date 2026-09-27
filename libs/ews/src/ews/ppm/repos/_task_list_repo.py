from db import BaseAsyncRepository

import db.models.ews as ews_models


class TaskListRepository(BaseAsyncRepository[ews_models.TaskList]):
    model_type = ews_models.TaskList
