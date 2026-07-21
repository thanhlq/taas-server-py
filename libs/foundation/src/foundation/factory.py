"""
A central place for providing actual implementations to the foundation library.
"""
from foundation.email.types import EmailServiceT
from foundation.resiliant.types import ResiliantServiceFactoryT
from foundation.utils.singleton import singleton


@singleton
class FoundationFactory:
    """
    Factory for settings
    """

    _resiliant_factory: ResiliantServiceFactoryT | None = None

    def __new__(cls, *args, **kwargs):
        raise RuntimeError("UtilityClass cannot be instantiated")

    @staticmethod
    def init_default_services():
        """
        Initialize the default services for the foundation library.
        This method is called during the application startup to register the default services.
        """
        from foundation.email.factory import EmailServiceFactory
        from foundation.state.service_registry import register_service

        # Register the default services
        register_service(EmailServiceT, EmailServiceFactory.get_email_service(), singleton=True)

        from foundation.storage.factory import StorageServiceFactory
        StorageServiceFactory()

    @staticmethod
    def use_resiliant(factory: ResiliantServiceFactoryT):
        """
        Set the resiliant service factory to be used by the application.
        """

        if FoundationFactory._resiliant_factory is not None:
            raise RuntimeError('Resiliant service factory has already been set.')

        from .resiliant import register_resiliant_factory

        register_resiliant_factory(factory)
        FoundationFactory._resiliant_factory = factory
