from __future__ import annotations

import db.models.core as m
from advanced_alchemy.extensions.fastapi import repository, service
from iam.constants import Roles


class UserService(service.SQLAlchemyAsyncRepositoryService[m.User]):
    """Handles database operations for users."""

    class Repo(repository.SQLAlchemyAsyncRepository[m.User]):
        """User SQLAlchemy Repository."""

        model_type = m.User

    repository_type = Repo
    default_role = Roles.USER
    match_fields = ['email']
