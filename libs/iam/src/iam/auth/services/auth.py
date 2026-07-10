from __future__ import annotations
from iam.auth.schemas import SignupRequest


import db.models.core as m
from advanced_alchemy.extensions.fastapi import repository, service
from iam.constants import Roles


class AuthService(service.SQLAlchemyAsyncRepositoryService[m.User]):
    class Repo(repository.SQLAlchemyAsyncRepository[m.User]):
        model_type = m.User

    repository_type = Repo
    default_role = Roles.USER
    match_fields = ['email']

    async def create_user(self, user: SignupRequest):
        """Create a new user with the default role."""
        user_row = self.user_create_to_db_user(user)
        return await self.create(user_row)
