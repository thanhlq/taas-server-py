from db import BaseAsyncRepository

import db.models.core as core_models


class UserRoleRepository(BaseAsyncRepository[core_models.UserRole]):
    model_type = core_models.UserRole
