from db import BaseAsyncRepository

import db.models.core as core_models


class UserRepository(BaseAsyncRepository[core_models.User]):
    model_type = core_models.User
