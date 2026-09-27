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

        FoundationFactory._register_resiliant_services(factory)
        FoundationFactory._resiliant_factory = factory

    @staticmethod
    def _register_resiliant_services(factory: ResiliantServiceFactoryT) -> None:
        """Expose the resiliant implementations to foundation code under their contracts."""
        from foundation.messaging.types import MessageRoutingServiceT
        from foundation.resiliant.dlq import IDLQService
        from foundation.resiliant.idempotency import IIdempotencyService
        from foundation.resiliant.outbox import IOutboxService, ITransactionOutboxService
        from foundation.resiliant.retry import IRetryPolicyFactory
        from foundation.resiliant.saga import ISagaService
        from foundation.resiliant.schedule import IScheduleService
        from foundation.state import register_service

        register_service(IOutboxService, factory.get_messaging_outbox_service())
        register_service(ITransactionOutboxService, factory.get_transaction_outbox_service())
        register_service(IDLQService, factory.get_dlq_service())
        register_service(IIdempotencyService, factory.get_idempotency_service())
        register_service(MessageRoutingServiceT, factory.get_message_routing_service())
        register_service(ISagaService, factory.get_saga_service())
        register_service(IScheduleService, factory.get_schedule_service())
        register_service(IRetryPolicyFactory, factory.get_retry_policy_factory())
        register_service(ResiliantServiceFactoryT, factory)
