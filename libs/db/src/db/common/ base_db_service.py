from advanced_alchemy.base import ModelProtocol
from advanced_alchemy.extensions.fastapi import service


class BaseDBService[ModelT: ModelProtocol](service.SQLAlchemyAsyncRepositoryService):
    """Base class for database services which normally internally use entiry repositories for actual database operations."""
