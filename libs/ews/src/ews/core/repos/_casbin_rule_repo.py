from db import BaseAsyncRepository

import db.models.core as core_models


class CasbinRuleRepository(BaseAsyncRepository[core_models.CasbinRule]):
    model_type = core_models.CasbinRule
