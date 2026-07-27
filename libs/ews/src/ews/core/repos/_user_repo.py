import db.models.core as core_models
from db import BaseAsyncRepository


class UserRepository(BaseAsyncRepository[core_models.User]):
    model_type = core_models.User

    # id_attribute = "id" # Overridden in BaseAsyncRepository
