from db import BaseAsyncRepository

import db.models.ews as ews_models


class CrmAccountRepository(BaseAsyncRepository[ews_models.CrmAccount]):
    model_type = ews_models.CrmAccount
