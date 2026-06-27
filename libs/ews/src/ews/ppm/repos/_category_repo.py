from db import BaseAsyncRepository

import db.models.ews as ews_models


class CategoryRepository(BaseAsyncRepository[ews_models.Category]):
    model_type = ews_models.Category
