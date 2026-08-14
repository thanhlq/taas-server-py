from foundation.messaging.events.flow_registration import (
    register_event_handlers_for_app_module,
)
from foundation.messaging.types import MessagingServiceT
from foundation.state import get_service, register_service
from foundation.utils.singleton import singleton

from iam import IamApplicationModule
from iam.auth.types import IamDirectoryServiceT
from iam.types import IIamServiceFactory


@singleton
class IamFactory:
    """
    The central factory class for instantiating the IAM related classes.

    Also for external directory service integration, this factory class can be used to get the directory service instance and the IAM service factory instance.
    """

    @staticmethod
    def initialize_iam(factory: IIamServiceFactory):
        """
        Initialize the IAM services as:
            - Register the IAM service factory instance in the service registry.
            - Register related event handlers
            - ...
        """
        IamFactory._set_iam_service_factory(factory)

        _messaging = IamFactory.get_messaging_service()
        register_event_handlers_for_app_module(app=IamApplicationModule(), msg_service=_messaging)
        # register_iam_handlers(msg_service=_messaging)
        # register_iam_schema_registry_schemas(_messaging)

    @staticmethod
    def get_messaging_service() -> MessagingServiceT:
        return get_service(MessagingServiceT)

    @staticmethod
    def get_iam_service_factory() -> 'IIamServiceFactory':
        return get_service(IIamServiceFactory)

    @staticmethod
    def get_directory_service() -> IamDirectoryServiceT:
        return get_service(IamDirectoryServiceT)

    @staticmethod
    def _set_iam_service_factory(factory: 'IIamServiceFactory') -> None:
        """
        Set the IAM service factory instance and register it in the service registry.
        This is normally implemented by packages as iam_keycloak, iam_ldap, etc. to provide the actual
        implementation of the IAM service factory.
        """
        register_service(IIamServiceFactory, factory)
        register_service(
            IamDirectoryServiceT, factory.get_directory_service()
        )  # Register with string key for backward compatibility
