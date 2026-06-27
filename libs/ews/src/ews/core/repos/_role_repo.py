from db import BaseAsyncRepository

import db.models.core as core_models


class RoleRepository(BaseAsyncRepository[core_models.Role]):
    model_type = core_models.Role
