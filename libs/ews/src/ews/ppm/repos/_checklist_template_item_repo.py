from db import BaseAsyncRepository

import db.models.ews as ews_models


class ChecklistTemplateItemRepository(BaseAsyncRepository[ews_models.ChecklistTemplateItem]):
    model_type = ews_models.ChecklistTemplateItem
