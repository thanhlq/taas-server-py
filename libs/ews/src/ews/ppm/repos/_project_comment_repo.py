from db import BaseAsyncRepository

import db.models.ews as ews_models


class ProjectCommentRepository(BaseAsyncRepository[ews_models.ProjectComment]):
    model_type = ews_models.ProjectComment
