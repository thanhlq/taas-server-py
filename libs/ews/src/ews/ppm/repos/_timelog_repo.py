from db import BaseAsyncRepository

import db.models.ews as ews_models


class TimelogRepository(BaseAsyncRepository[ews_models.Timelog]):
    model_type = ews_models.Timelog
