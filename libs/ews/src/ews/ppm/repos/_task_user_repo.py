from db import BaseAsyncRepository

import db.models.ews as ews_models


class TaskUserRepository(BaseAsyncRepository[ews_models.TaskUser]):
    model_type = ews_models.TaskUser
