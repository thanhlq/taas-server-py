import logging
from typing import TYPE_CHECKING, Any

from platform_core.serialization import decode_json, encode_json
from sqlalchemy import AsyncAdaptedQueuePool, NullPool, event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

if TYPE_CHECKING:
    from platform_core.config import DatabaseSettings

logger = logging.getLogger('EngineFactory')


class EngineFactory:
    _engine: dict[str, AsyncEngine] = {}

    @staticmethod
    def get_sqlalchemy_engine(settings: 'DatabaseSettings') -> AsyncEngine:
        eng = EngineFactory._engine.get(settings.URL)
        if eng is None:
            eng = _create_sqlalchemy_engine(settings)
            EngineFactory._engine[settings.URL] = eng
            logger.info(
                msg=f'🐬 Created new SQLAlchemy engine for URL: {eng.url.render_as_string(hide_password=True)}'
            )
        return eng


def _create_sqlalchemy_engine(db_settings: 'DatabaseSettings') -> 'AsyncEngine':
    """
    The entry point for creating the SQLAlchemy engine. This function is used by the `SQLAlchemyAsyncConfig`
    dataclass to create the engine based on the provided settings.

    Should be cached?
    """
    url = db_settings.URL.replace('postgresql://', 'postgresql+psycopg://')

    if url.startswith('postgresql+asyncpg'):
        # Build engine kwargs - pool args are invalid with NullPool
        engine_kwargs: dict[str, Any] = {
            'url': url,
            'future': True,
            'json_serializer': encode_json,
            'json_deserializer': decode_json,
            'echo': db_settings.ECHO,
            'echo_pool': db_settings.ECHO_POOL,
            'poolclass': AsyncAdaptedQueuePool,
            'pool_recycle': db_settings.POOL_RECYCLE,
            'pool_pre_ping': db_settings.POOL_PRE_PING,
        }
        if db_settings.POOL_DISABLED:
            engine_kwargs['poolclass'] = NullPool
        else:
            engine_kwargs.update(
                {
                    'max_overflow': db_settings.POOL_MAX_OVERFLOW,
                    'pool_size': db_settings.POOL_SIZE,
                    'pool_timeout': db_settings.POOL_TIMEOUT,
                    'pool_use_lifo': True,
                }
            )
        engine = create_async_engine(**engine_kwargs)
        """Database session factory.

        See [`async_sessionmaker()`][sqlalchemy.ext.asyncio.async_sessionmaker].
        """

        @event.listens_for(engine.sync_engine, 'connect')
        def _sqla_on_connect(  # pragma: no cover # pyright: ignore[reportUnusedFunction]
            dbapi_connection: Any,
            _: Any,
        ) -> Any:  # pragma: no cover
            """Using msgspec for serialization of the json column values means that the
            output is binary, not `str` like `json.dumps` would output.
            SQLAlchemy expects that the json serializer returns `str` and calls `.encode()` on the value to
            turn it to bytes before writing to the JSONB column. I'd need to either wrap `serialization.to_json` to
            return a `str` so that SQLAlchemy could then convert it to binary, or do the following, which
            changes the behaviour of the dialect to expect a binary value from the serializer.
            See Also https://github.com/sqlalchemy/sqlalchemy/blob/14bfbadfdf9260a1c40f63b31641b27fe9de12a0/lib/sqlalchemy/dialects/postgresql/asyncpg.py#L934  pylint: disable=line-too-long
            """

            def encoder(bin_value: bytes) -> bytes:
                return b'\x01' + bin_value

            def decoder(bin_value: bytes) -> Any:
                # the byte is the \x01 prefix for jsonb used by PostgreSQL.
                # asyncpg returns it when format='binary'
                return decode_json(bin_value[1:])

            dbapi_connection.await_(
                dbapi_connection.driver_connection.set_type_codec(
                    'jsonb',
                    encoder=encoder,
                    decoder=decoder,
                    schema='pg_catalog',
                    format='binary',
                ),
            )
            dbapi_connection.await_(
                dbapi_connection.driver_connection.set_type_codec(
                    'json',
                    encoder=encoder,
                    decoder=decoder,
                    schema='pg_catalog',
                    format='binary',
                ),
            )

    elif url.startswith('sqlite+aiosqlite'):
        engine = create_async_engine(
            url=url,
            future=True,
            json_serializer=encode_json,
            json_deserializer=decode_json,
            echo=db_settings.ECHO,
            echo_pool=db_settings.ECHO_POOL,
            pool_recycle=db_settings.POOL_RECYCLE,
            pool_pre_ping=db_settings.POOL_PRE_PING,
        )
        """Database session factory.

        See [`async_sessionmaker()`][sqlalchemy.ext.asyncio.async_sessionmaker].
        """

        @event.listens_for(engine.sync_engine, 'connect')
        def _sqla_on_connect(  # pragma: no cover # pyright: ignore[reportUnusedFunction]
            dbapi_connection: Any,
            _: Any,
        ) -> Any:
            """Override the default begin statement.  The disables the built in begin execution."""
            dbapi_connection.isolation_level = None

        @event.listens_for(engine.sync_engine, 'begin')
        def _sqla_on_begin(  # pragma: no cover # pyright: ignore[reportUnusedFunction]
            dbapi_connection: Any,
        ) -> Any:
            """Emits a custom begin"""
            dbapi_connection.exec_driver_sql('BEGIN')

    else:
        # Build engine kwargs - pool args are invalid with NullPool
        engine_kwargs = {
            'url': url,
            'future': True,
            'json_serializer': encode_json,
            'json_deserializer': decode_json,
            'echo': db_settings.ECHO,
            'echo_pool': db_settings.ECHO_POOL,
            'pool_recycle': db_settings.POOL_RECYCLE,
            'pool_pre_ping': db_settings.POOL_PRE_PING,
            'poolclass': AsyncAdaptedQueuePool,
            'connect_args': {
                # default 5, 1 for testing
                'prepare_threshold': 0
                },
        }
        if db_settings.POOL_DISABLED:
            engine_kwargs['poolclass'] = NullPool
            print('Creating SQLAlchemy engine with NullPool (pooling disabled)')
        else:
            engine_kwargs.update(
                {
                    'max_overflow': db_settings.POOL_MAX_OVERFLOW,
                    'pool_size': db_settings.POOL_SIZE,
                    'pool_timeout': db_settings.POOL_TIMEOUT,
                    'pool_use_lifo': True,
                }
            )
            print(f'Creating SQLAlchemy engine with pool_size={db_settings.POOL_SIZE}, max_overflow={db_settings.POOL_MAX_OVERFLOW}, pool_timeout={db_settings.POOL_TIMEOUT}')
        engine = create_async_engine(**engine_kwargs)
    return engine
