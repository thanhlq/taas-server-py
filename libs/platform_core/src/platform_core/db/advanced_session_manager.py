"""
Asynchronous database session manager.
"""

import contextlib
import contextvars
import inspect
import logging
from asyncio import gather
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Iterable
from functools import wraps
from typing import Optional, Union, get_args, get_type_hints

from platform_core.concurrency import get_current_task_id
from platform_core.config import DatabaseSettings, get_settings
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_scoped_session,
    async_sessionmaker,
)

_current_context_session: contextvars.ContextVar[Optional[AsyncSession]] = (
    contextvars.ContextVar('current_db_session', default=None)
)
# Context variable to track call depth
_call_depth: contextvars.ContextVar[int] = contextvars.ContextVar(
    'call_depth', default=0
)

logger = logging.getLogger()


class AdvancedSessionManager:
    _sessionmaker: async_sessionmaker[AsyncSession]

    def __init__(self, db_settings: DatabaseSettings | None = None):
        if db_settings is None:
            # For MAIN DB
            db_settings = get_settings().db
        self._engine = db_settings.get_engine()
        self._sessionmaker = async_sessionmaker(
            autocommit=False,
            bind=self._engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )
        logger.debug('🐬 AdvancedSessionManager initialized.')

    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        return self._sessionmaker

    def get_session(self) -> AsyncSession:
        return self._sessionmaker()

    @contextlib.asynccontextmanager
    async def connect(self) -> AsyncIterator[AsyncConnection]:
        if self._engine is None:
            raise Exception('AdvancedSessionManager is not initialized')

        async with self._engine.begin() as connection:
            try:
                yield connection
            except Exception:
                await connection.rollback()
                raise

    # @contextlib.asynccontextmanager
    # async def get_session_generator(self) -> AsyncIterator[AsyncSession]:
    #     session = self.get_session()
    #     try:
    #         yield session
    #     except Exception as e:
    #         await session.rollback()
    #         raise e
    #     finally:
    #         await session.close()

    def is_transaction_context(self) -> bool:
        """Returns True if currently within a db_transaction context."""
        return _current_context_session.get() is not None

    def get_current_context_session(self) -> AsyncSession | None:
        # global _current_context_session
        return _current_context_session.get()

    @contextlib.asynccontextmanager
    async def get_session_generator(
        self, auto_commit: bool = True
    ) -> AsyncIterator[AsyncSession]:
        """
        A generator that yields a session within a context variable.
        The returned session can be shared across multiple calls.
        """
        # global _current_context_session
        existing_session = _current_context_session.get()

        if existing_session is not None:
            # Already in transaction context, reuse session
            yield existing_session
        else:
            # Start new transaction
            async with self.get_session() as session:
                session_token = _current_context_session.set(session)
                try:
                    yield session
                    if auto_commit:
                        logger.debug('🐬 [get_session_generator] Committing session')
                        await session.commit()
                except Exception as e:
                    await session.rollback()
                    raise e
                finally:
                    _current_context_session.reset(session_token)
                    # await session.close()

    async def close(self):
        if self._engine is not None:
            await self._engine.dispose()

        self._engine = None
        self._sessionmaker = None  # type: ignore


class MainDatabase:
    _instance: AdvancedSessionManager | None = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = AdvancedSessionManager()
        return cls._instance

    @classmethod
    def get_instance(cls) -> 'AdvancedSessionManager':
        if cls._instance is None:
            cls._instance = AdvancedSessionManager()
        return cls._instance


class DBConcurrentSessionFactory:
    _scoped_session_factory: async_scoped_session[AsyncSession]

    def __init__(self, db: AdvancedSessionManager | None = None):
        if db is None:
            db = MainDatabase.get_instance()
        self._db = db
        self._scoped_session_factory = async_scoped_session(
            self._db.session_factory(), scopefunc=get_current_task_id
        )

    def get_session(self) -> AsyncSession:
        return self._scoped_session_factory()

    @property
    def scoped_session_factory(self) -> async_scoped_session[AsyncSession]:
        return self._scoped_session_factory

    @staticmethod
    async def close_sessions(sessions: Iterable[AsyncSession]):
        await gather(*[each_session.close() for each_session in sessions])

    @staticmethod
    async def commit_sessions(sessions: Iterable[AsyncSession]):
        await gather(*[each_session.commit() for each_session in sessions])

    @staticmethod
    async def rollback_sessions(sessions: Iterable[AsyncSession]):
        await gather(*[each_session.rollback() for each_session in sessions])


async def get_db_async_generator() -> AsyncGenerator[AsyncSession]:
    async with MainDatabase.get_instance().get_session_generator() as session:
        yield session


# def db_session(func: Callable) -> Callable:
#     @wraps(func)
#     async def wrapper(*args, **kwargs):
#         async with MainDBAsyncSessionManager.get_instance().get_session_generator() as session:
#             return await func(*args, session=session, **kwargs)

#     return wrapper


def db_session(_func: Union[Callable, None] = None, *, transaction: bool = False):
    """
    A decorator to provide a database session to the decorated async function.
     - This session is not transactional and will not be committed automatically.
     - The user of this decorator is responsible for committing or rolling back the session.
     - This session will be instantiated and not reused from context (Local Thread).

    🔥 IMPORTANT: consider using `db_context_session` for automatic context-aware session management.
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            async with MainDatabase.get_instance().get_session_generator() as session:
                try:
                    result = await func(*args, session=session, **kwargs)
                    if transaction:
                        await session.commit()
                    return result
                except Exception as e:
                    await session.rollback()
                    logger.error(
                        f"Database operation failed in function '{getattr(func, '__name__', 'unknown')}': {str(e)}"
                    )
                    raise e
                finally:
                    await session.close()

        return wrapper

    if _func is None:
        return decorator
    else:
        return decorator(_func)


count = 0


def _resolve_injected_param_name(func: Callable, target_type: type, fallback: str) -> str:
    signature = inspect.signature(func)
    try:
        hints = get_type_hints(func, include_extras=True)
    except Exception:
        hints = getattr(func, '__annotations__', {}) or {}

    for name, param in signature.parameters.items():
        if name in {'self', 'cls'}:
            continue

        hint = hints.get(name, param.annotation)
        if hint is inspect.Parameter.empty:
            continue

        if hasattr(hint, '__metadata__'):
            hint = get_args(hint)[0]

        args = get_args(hint)
        if hint is target_type:
            return name
        if target_type in args:
            return name

    return fallback


def db_context_session(
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
        injected_param_name = _resolve_injected_param_name(func, AsyncSession, 'session')

        @wraps(func)
        async def wrapper(*args, **kwargs):
            current_depth = _call_depth.get()
            existing_session = MainDatabase.get_instance().get_current_context_session()
            kwargs.pop(injected_param_name, None)

            if existing_session is not None:
                # Use existing session from context - pass it in kwargs
                # kwargs['session'] = existing_session
                print(
                    f'♻️ 🐬 [db_context_session] Reusing existing session (depth: {current_depth})'
                )

                return await func(
                    *args, **{**kwargs, injected_param_name: existing_session}
                )
            else:
                # Create new session (legacy behavior for non-transaction calls)
                # async with db_context_transaction(transaction) as new_session:
                # No existing session, create a new transaction context
                # Increment call depth to track we're the root caller
                depth_token = _call_depth.set(current_depth + 1)
                try:
                    async with MainDatabase.get_instance().get_session_generator(
                        transaction
                    ) as new_session:
                        global count
                        print(
                            f'🐬 [db_session] New session created: {count} (depth: {current_depth + 1})'
                        )
                        count += 1
                        # kwargs['session'] = new_session
                        result = await func(
                            *args, **{**kwargs, injected_param_name: new_session}
                        )
                        return result
                finally:
                    # await new_session.close()
                    _call_depth.reset(depth_token)
                    # new_session.close()

        return wrapper

    if _func is None:
        return decorator
    else:
        return decorator(_func)



# ref https://medium.com/@lironbenyeda/fastapi-sqlalchemy-and-parallel-queries-walk-into-a-bar-86dfe40aa878
async def get_db_concurrent_sesson_manager() -> AsyncGenerator[
    DBConcurrentSessionFactory
]:
    cs_manager = DBConcurrentSessionFactory()
    try:
        yield cs_manager
    finally:
        sessions = cs_manager.scoped_session_factory.registry.registry.values()
        await DBConcurrentSessionFactory.close_sessions(sessions)


def db_concurrent_session(func):
    injected_param_name = _resolve_injected_param_name(
        func, async_sessionmaker[AsyncSession], 'session'
    )

    @wraps(func)
    async def wrapper(*args, **kwargs):
        cs_manager = DBConcurrentSessionFactory()
        kwargs.pop(injected_param_name, None)
        try:
            a_session: async_scoped_session[AsyncSession] = cs_manager.scoped_session_factory
            result = await func(*args, **{**kwargs, injected_param_name: a_session})
            return result
        except Exception as e:
            sessions = cs_manager.scoped_session_factory.registry.registry.values()
            await DBConcurrentSessionFactory.rollback_sessions(sessions)
            raise e
        finally:
            sessions = cs_manager.scoped_session_factory.registry.registry.values()
            await DBConcurrentSessionFactory.commit_sessions(sessions)
            await DBConcurrentSessionFactory.close_sessions(sessions)

    return wrapper
