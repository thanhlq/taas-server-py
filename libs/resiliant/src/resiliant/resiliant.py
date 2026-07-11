from logging import Logger

from foundation.observability.log_factory import LogFactory
from foundation.resiliant.outbox import IOutboxRepository, OutboxConfig, OutboxFactory
from src.resiliant.outbox.outbox_repository import OutboxRepository


class ResiliantFactory:
    """
    A centralized factory for creating and managing Resiliant components, including Outbox and DLQ repositories.
    This factory is responsible for initializing the repositories with the provided configuration and ensuring that they are accessible
    """

    _logger: Logger | None = None

    @staticmethod
    def logger():
        if ResiliantFactory._logger is None:
            ResiliantFactory._logger = LogFactory().get_logger('ResiliantFactory')
        return ResiliantFactory._logger



    @staticmethod
    @staticmethod
    def get_outbox_repository(config: OutboxConfig | None = None) -> IOutboxRepository:
        if (config is None):
            ResiliantFactory.logger().info("No OutboxConfig provided. Using default configuration.")
            config = OutboxConfig()  # Use default configuration if none provided
        return OutboxRepository(config)

    @staticmethod
    def get_outbox_service(config: OutboxConfig | None = None):
        OutboxFactory(
            repository=ResiliantFactory.get_outbox_repository(config),
            publisher=None,  # Publisher can be set later or injected as needed
            config=config,
        ).create_service()
