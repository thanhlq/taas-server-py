from db import BaseAsyncRepository

import db.models.core as core_models


class TagRepository(BaseAsyncRepository[core_models.Tag]):
    model_type = core_models.Tag
