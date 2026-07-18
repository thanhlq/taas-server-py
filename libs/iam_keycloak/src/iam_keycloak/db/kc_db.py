"""
Since Keycloak is a separate database, This class is for managing Keycloak database instance
"""

from collections.abc import Callable
from functools import wraps
from typing import Union

from foundation.db.advanced_db_manager import AdvancedDBManager

from .kc_db_settings import get_keycloak_db_settings


class KeycloakDBManager(AdvancedDBManager):
    _instance = None

    def __init__(self):
        settings = get_keycloak_db_settings()
        super().__init__(settings)


kc_db = KeycloakDBManager()


# def kc_db_session_async(func: Callable) -> Callable:
#     """
#     Decorator to manage Keycloak database session for asynchronous functions.
#     Keycloak related repository functions should use this decorator.
#     """

#     @wraps(func)
#     async def wrapper(*args, **kwargs):
#         async with db.get_session_generator() as session:
#             try:
#                 result = await func(*args, session=session, **kwargs)
#                 # No commit should be done by the user of this decorator,
#                 # await session.commit()
#                 return result
#             except Exception:
#                 await session.rollback()
#                 raise
#             finally:
#                 await session.close()

#     return wrapper


def kc_db_session_async(
    _func: Union[Callable, None] = None, *, transaction: bool = False
):
    """
    Context-aware decorator that automatically reuses existing session from context
    if available, otherwise creates a new session.

    This decorator automatically establishes a transaction context on the first call
    in a call stack and reuses it for all nested calls, even if the parent function
    is not decorated.
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # current_depth = _call_depth.get()
            existing_session = kc_db.get_current_context_session()

            if existing_session is not None:
                # Use existing session from context - pass it in kwargs
                # kwargs['session'] = existing_session
                return await func(*args, session=existing_session, **kwargs)
            else:
                # Create new session (legacy behavior for non-transaction calls)
                # async with db_context_transaction(transaction) as new_session:
                # No existing session, create a new transaction context
                # Increment call depth to track we're the root caller
                async with kc_db.get_session_generator(transaction) as new_session:
                    result = await func(*args, session=new_session, **kwargs)
                    return result

        return wrapper

    if _func is None:
        return decorator
    else:
        return decorator(_func)
