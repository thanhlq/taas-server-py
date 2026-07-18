from abc import ABC
from typing import Any, cast

from advanced_alchemy.base import ModelProtocol
from db import BaseAsyncRepository
from db.models import User
from db.repository import IRepositoryFactory
from ews.core import CoreRepositoryFactory
from ews.core.repos import TenantRepository, UserRepository
from ews.core.repos._organization_repo import OrganizationRepository
from foundation import BaseService
from foundation.db.types import DBAsyncScopedSession, DBAsyncSession
from foundation.messaging.events.event_handler import BaseEventHandler

from iam.admin.services import AdminService, get_admin_service
from iam.auth.types import IamDirectoryServiceT
from iam.types import IIamServiceFactory


class BaseIamService(BaseService, ABC):
    """Base class for IAM services."""

    @property
    def directory_service(self) -> IamDirectoryServiceT:
        """
        Get the directory service instance.
        """
        return self.get_service(IamDirectoryServiceT)

    @property
    def iam_service_factory(self) -> IIamServiceFactory:
        """
        Get the IAM service factory instance.
        """
        return self.get_service(IIamServiceFactory)

    @property
    def directory_repository_factory(self) -> IRepositoryFactory:
        """
        Get the repository factory instance of the actual directory platform (i.e. linked to keycloak DB).
        """
        return self.iam_service_factory.get_repository_factory()

    def get_repository(
        self, model: type[ModelProtocol], session: DBAsyncSession | DBAsyncScopedSession
    ) -> BaseAsyncRepository:
        return CoreRepositoryFactory.get_repo_by_model(model, session)

    def get_user_repository(self, session: DBAsyncSession | DBAsyncScopedSession) -> UserRepository:
        return cast(UserRepository, self.get_repository(User, session))

    def get_tenant_repository(self, session: DBAsyncSession | DBAsyncScopedSession) -> TenantRepository:
        return cast(TenantRepository, self.get_repository(TenantRepository.model_type, session))

    def get_organization_repository(self, session: DBAsyncSession | DBAsyncScopedSession) -> OrganizationRepository:
        return cast(OrganizationRepository, self.get_repository(OrganizationRepository.model_type, session))


class BaseIamEventHandler[EventT: Any](BaseEventHandler[EventT], ABC):
    """
    Base class for IAM event handlers.
    """

    def __init__(
        self,
        event_class: type[EventT] | None = None,
        handler_name: str | None = None,
        **kwargs,
    ):
        super().__init__(event_class=event_class, handler_name=handler_name, **kwargs)

    @property
    def directory_service(self) -> IamDirectoryServiceT:
        """
        Get the directory service instance.
        """
        return self.get_service(IamDirectoryServiceT)

    @property
    def iam_service_factory(self) -> IIamServiceFactory:
        """
        Get the IAM service factory instance.
        """
        return self.get_service(IIamServiceFactory)

    def get_admin_service(self) -> AdminService:
        """
        Get the admin service instance.
        """
        return get_admin_service()

    @property
    def repository_factory(self) -> IRepositoryFactory:
        """
        Get the repository factory instance.
        """
        return self.iam_service_factory.get_repository_factory()
