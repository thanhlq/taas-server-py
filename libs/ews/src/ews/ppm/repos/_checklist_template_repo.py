from db import BaseAsyncRepository

import db.models.ews as ews_models


class ChecklistTemplateRepository(BaseAsyncRepository[ews_models.ChecklistTemplate]):
    model_type = ews_models.ChecklistTemplate
