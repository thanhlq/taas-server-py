from db import BaseAsyncRepository

import db.models.ews as ews_models


class PayrateRepository(BaseAsyncRepository[ews_models.Payrate]):
    model_type = ews_models.Payrate
