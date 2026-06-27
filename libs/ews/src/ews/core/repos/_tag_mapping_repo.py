from db import BaseAsyncRepository

import db.models.core as core_models


class TagMappingRepository(BaseAsyncRepository[core_models.TagMapping]):
    model_type = core_models.TagMapping
