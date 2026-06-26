"""
Asynchronous database session manager.
"""

from .analytics import DBSessionStats

import contextlib
import contextvars
import inspect
import logging
from asyncio import gather, current_task
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


_current_context_session: contextvars.ContextVar[Optional[tuple[int, AsyncSession]]] = (
    contextvars.ContextVar('current_db_session', default=None)
)

# Context variable to track call depth
_call_depth: contextvars.ContextVar[int] = contextvars.ContextVar(
    'call_depth', default=0
)

logger = logging.getLogger('DB')


class _TrackedScopedSessionFactory:
    def __init__(self, factory: async_scoped_session[AsyncSession]):
        self._factory = factory

    def __call__(self) -> AsyncSession:
        session = self._factory()
        scoped_session_stats.increment_created()
        return session

    def __getattr__(self, name: str):
        return getattr(self._factory, name)


class AdvancedDBManager:
    """Base class for managing asynchronous database sessions and connections."""

    _sessionmaker: async_sessionmaker[AsyncSession]
    _debug: bool = False

    def __init__(self, db_settings: DatabaseSettings | None = None):
        if db_settings is None:
            # For MAIN DB
            db_settings = get_settings().db
            if db_settings.DEBUG:
                self._debug = True
        self._engine = db_settings.get_engine()
        self._sessionmaker = async_sessionmaker(
            autocommit=False,
            bind=self._engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )
        self.session_stats = DBSessionStats(logger, debug=self._debug)
        """
        For tracing of session usage, including creation, commit, rollback, and close operations.
        Normally this is used for db_context_session,
        """
        if self._debug:
            logger.debug('🐬 AdvancedDBManager initialized.')

    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        return self._sessionmaker

    def new_session(self) -> AsyncSession:
        s = self._sessionmaker()
        self.session_stats.increment_created()
        return s

    @contextlib.asynccontextmanager
    async def connect(self) -> AsyncIterator[AsyncConnection]:
        if self._engine is None:
            raise Exception('AdvancedDBManager is not initialized')

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

    # def get_current_context_session(self) -> AsyncSession | None:
    #     # global _current_context_session
    #     return _current_context_session.get()

    def get_current_context_session(self) -> Optional[AsyncSession]:
        ctx = _current_context_session.get()
        if ctx is None:
            return None
        task_id, session = ctx
        # If we're in a different task (e.g., a child task spawned by asyncio.gather
        # that inherited the parent's ContextVar copy), don't reuse the parent's session.
        current_task_id = id(current_task())
        if task_id != current_task_id:
            return None

        self.session_stats.increment_reused()

        return session

    @contextlib.asynccontextmanager
    async def get_session_generator(
        self, auto_commit: bool = True
    ) -> AsyncIterator[AsyncSession]:
        """
        A generator that yields a session within a context variable.
        The returned session can be shared across multiple calls.
        """
        # global _current_context_session
        existing_session = self.get_current_context_session()

        if existing_session is not None:
            # Already in transaction context, reuse session
            yield existing_session
        else:
            # Start new transaction
            async with self.new_session() as session:
                session_token = _current_context_session.set((id(current_task()), session))
                # session_token = _db_current_session.set((id(current_task()), session))
                try:
                    yield session
                    if auto_commit:
                        await self.commit_session(session)
                except Exception as e:
                    await self.rollback_session(session)
                    raise e
                finally:
                    _current_context_session.reset(session_token)
                    # await session.close()

    async def commit_session(self, session: AsyncSession):
        await session.commit()
        self.session_stats.increment_committed()

    async def rollback_session(self, session: AsyncSession):
        await session.rollback()
        self.session_stats.increment_rolled_back()

    async def close_session(self, session: AsyncSession):
        await session.close()
        self.session_stats.increment_closed()

    async def close(self):
        if self._engine is not None:
            await self._engine.dispose()

        self._engine = None
        self._sessionmaker = None  # type: ignore


class MainDatabase:
    _instance: AdvancedDBManager | None = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = AdvancedDBManager()
        return cls._instance

    @classmethod
    def get_instance(cls) -> 'AdvancedDBManager':
        if cls._instance is None:
            cls._instance = AdvancedDBManager()
        return cls._instance


class ConcurrentSessionFactory:
    """
    Centralized factory for managing concurrent database sessions. Each concurrent operation gets its own session, but they are all tracked
    and can be committed or rolled back together.
    """

    _scoped_session_factory: async_scoped_session[AsyncSession]
    # class variable to track session statistics
    scoped_session_stats: DBSessionStats = None
    _debug: bool = False

    def __init__(self, db: AdvancedDBManager | None = None):
        if db is None:
            db = MainDatabase.get_instance()
            self._debug = db._debug
        self._db = db
        self._scoped_session_factory = async_scoped_session(
            self._db.session_factory(), scopefunc=get_current_task_id
        )
        self._tracked_scoped_session_factory = _TrackedScopedSessionFactory(
            self._scoped_session_factory
        )

        if not ConcurrentSessionFactory.scoped_session_stats:
            ConcurrentSessionFactory.scoped_session_stats = DBSessionStats(
                logger, debug=self._db._debug
            )

    def new_scoped_session(self) -> AsyncSession:
        s = self._tracked_scoped_session_factory()
        ConcurrentSessionFactory.scoped_session_stats.increment_created()
        return s

    @property
    def scoped_session_factory(self) -> async_scoped_session[AsyncSession]:
        """
        Returns a factory that provides a scoped session for concurrent operations.

        Examples:
            concurrent_session_factory = ConcurrentSessionFactory()
            async with concurrent_session_factory.scoped_session_factory() as session:
                # Use the session for database operations
                ...
        """
        return self._tracked_scoped_session_factory

    @staticmethod
    async def close_sessions(sessions: Iterable[AsyncSession]):
        sessions_list = list(sessions)
        ConcurrentSessionFactory.scoped_session_stats.increment_closed(
            len(sessions_list)
        )
        await gather(*[each_session.close() for each_session in sessions_list])

    @staticmethod
    async def commit_sessions(sessions: Iterable[AsyncSession]):
        # sessions_list = list(sessions)
        ConcurrentSessionFactory.scoped_session_stats.increment_committed(len(sessions))
        await gather(*[each_session.commit() for each_session in sessions])

    @staticmethod
    async def rollback_sessions(sessions: Iterable[AsyncSession]):
        # sessions_list = list(sessions)
        ConcurrentSessionFactory.scoped_session_stats.increment_rolled_back(
            len(sessions)
        )
        await gather(*[each_session.rollback() for each_session in sessions])


# async def get_db_async_generator() -> AsyncGenerator[AsyncSession]:
#     async with MainDatabase.get_instance().get_session_generator() as session:
#         yield session


def _resolve_injected_param_name(
    func: Callable, target_type: type, fallback: str
) -> str:
    """What is the purpose of this function? It inspects the signature of a function to find the parameter name that matches a given target type. If no matching parameter is found, it returns a fallback name."""
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
    _func: Union[Callable, None] = None, *, auto_commit: bool = False
):
    """
    Context-aware decorator that automatically reuses existing session from context
    if available, otherwise creates a new session.

    This decorator automatically establishes a transaction context on the first call
    in a call stack and reuses it for all nested calls, even if the parent function
    is not decorated.
    """

    def decorator(func: Callable) -> Callable:
        injected_param_name = _resolve_injected_param_name(
            func, AsyncSession, 'session'
        )

        @wraps(func)
        async def wrapper(*args, **kwargs):
            current_depth = _call_depth.get()
            existing_session = MainDatabase.get_instance().get_current_context_session()
            kwargs.pop(injected_param_name, None)

            if existing_session is not None:
                # Use existing session from context - pass it in kwargs
                # kwargs['session'] = existing_session
                if db_debug:
                    logger.debug(
                        f'🐬 🗃️ [db_context_session] Reusing existing session (depth: {current_depth})'
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
                        auto_commit
                    ) as new_session:
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
    ConcurrentSessionFactory
]:
    cs_manager = ConcurrentSessionFactory()
    try:
        yield cs_manager
    finally:
        sessions = cs_manager.scoped_session_factory.registry.registry.values()
        await ConcurrentSessionFactory.close_sessions(sessions)


def db_concurrent_session(func):
    injected_param_name = _resolve_injected_param_name(
        func, async_sessionmaker[AsyncSession], 'session'
    )

    @wraps(func)
    async def wrapper(*args, **kwargs):
        cs_manager = ConcurrentSessionFactory()
        kwargs.pop(injected_param_name, None)
        try:
            _scoped_session_fac: async_scoped_session[AsyncSession] = (
                cs_manager.scoped_session_factory
            )
            result = await func(
                *args, **{**kwargs, injected_param_name: _scoped_session_fac}
            )
            return result
        except Exception as e:
            sessions = cs_manager.scoped_session_factory.registry.registry.values()
            await ConcurrentSessionFactory.rollback_sessions(sessions)
            raise e
        finally:
            sessions = cs_manager.scoped_session_factory.registry.registry.values()
            await ConcurrentSessionFactory.commit_sessions(sessions)
            await ConcurrentSessionFactory.close_sessions(sessions)

    return wrapper
