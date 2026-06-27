from db import BaseAsyncRepository

import db.models.core as core_models

class RoleRepository(BaseAsyncRepository[core_models.Role]):
    """
    Repository for managing Role entities in the database.
    Inherits from BaseAsyncRepository to provide asynchronous CRUD operations.

    Specific functions for Role entities can be added here as needed.
    """
    model_type = core_models.Role
