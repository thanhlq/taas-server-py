from db import BaseAsyncRepository

import db.models.ews as ews_models


class PayrunRepository(BaseAsyncRepository[ews_models.Payrun]):
    model_type = ews_models.Payrun
