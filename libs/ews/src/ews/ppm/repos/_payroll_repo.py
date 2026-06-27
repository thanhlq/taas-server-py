from db import BaseAsyncRepository

import db.models.ews as ews_models


class PayrollRepository(BaseAsyncRepository[ews_models.Payroll]):
    model_type = ews_models.Payroll
