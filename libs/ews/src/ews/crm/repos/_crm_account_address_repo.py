from db import BaseAsyncRepository

import db.models.ews as ews_models


class CrmAccountAddressRepository(BaseAsyncRepository[ews_models.CrmAccountAddress]):
    model_type = ews_models.CrmAccountAddress
