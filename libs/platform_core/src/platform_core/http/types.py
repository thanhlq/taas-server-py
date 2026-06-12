from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_scoped_session

from platform_core.db.advanced_session_manager import DBConcurrentSessionFactory
from platform_core.db.types import DBAsyncScopedSession, DBAsyncSession

CONTROLLER_PARAM_INJECTED_TYPES = {
    AsyncSession,
    async_scoped_session[AsyncSession],
    DBAsyncSession,
    DBAsyncScopedSession,
    DBConcurrentSessionFactory,
}
""" Set of types that are injected into controller methods by decorators, such as DB sessions. This is used by the framework to determine which dependencies to provide when invoking controller methods."""


def get_controller_injected_types() -> set[Any]:
    """Returns a list of types that are injected into controller methods by decorators, such as DB sessions. This is used by the framework to determine which dependencies to provide when invoking controller methods."""
    return CONTROLLER_PARAM_INJECTED_TYPES
