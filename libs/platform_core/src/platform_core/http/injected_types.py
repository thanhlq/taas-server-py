from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.db.advanced_session_manager import DBConcurrentSessionFactory

INJECTED_TYPES = set(
    [
        AsyncSession,
        DBConcurrentSessionFactory,
    ]
)


def get_controller_injected_typeS() -> set[Any]:
    """Returns a list of types that are injected into controller methods by decorators, such as DB sessions. This is used by the framework to determine which dependencies to provide when invoking controller methods."""
    return INJECTED_TYPES
