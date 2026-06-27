from db import BaseAsyncRepository

import db.models.ews as ews_models


class PayrateAdjustmentRepository(BaseAsyncRepository[ews_models.PayrateAdjustment]):
    model_type = ews_models.PayrateAdjustment
