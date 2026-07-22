import asyncio
import logging

from sqlalchemy import inspect
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from sqlalchemy.orm import RelationshipProperty

logger = logging.getLogger(__name__)


def _check_models_against_connection(connection: Connection, Base) -> bool:
    """Consistency-check body, run against a *sync* :class:`Connection`.

    ``inspect()`` only accepts a sync ``Connection``/``Engine``; async callers
    obtain one via :meth:`AsyncConnection.run_sync`.
    """
    iengine = inspect(connection)
    errors = False

    tables = iengine.get_table_names()

    # SQLAlchemy 2.0: iterate the mapped classes via the registry. The old
    # ``Base._decl_class_registry`` (and its ``_ModuleMarker`` entries) was
    # removed in 1.4+, so ``registry.mappers`` is the supported replacement.
    for mapper in Base.registry.mappers:
        klass = mapper.class_

        # Keycloak models share advanced_alchemy's global registry, but their
        # tables live in the separate Keycloak-managed database (not the main
        # application DB), so they must not be validated here.
        if klass.__module__.startswith('iam_keycloak.'):
            logger.info(f'Skipping Keycloak model {klass} (external database)')
            continue

        table = klass.__tablename__

        logger.info(f'🐘 📁 Checking model {klass} with table {table} against the database')

        if table not in tables:
            logger.error(
                'Model %s declares table %s which does not exist in the database',
                klass,
                table,
            )
            errors = True
            continue

        # Check all declared columns exist in the database table.
        # get_columns() looks like:
        #   [{'name': 'id', 'type': INTEGER(), 'nullable': False, ...}]
        columns = {c['name'] for c in iengine.get_columns(table)}

        for column_prop in mapper.attrs:
            if isinstance(column_prop, RelationshipProperty):
                # TODO: Add sanity checks for relations
                logger.info(f'🐘 📁 Ignoring relationship property {column_prop}')
                continue

            for column in column_prop.columns:
                # Assume normal flat column
                if column.key not in columns:
                    logger.error(
                        f'🐘 ❌ Model {klass} declares column {column.key} which does not exist in table {table}',
                    )
                    errors = True
                else:
                    logger.info(
                        f'🐘 ✅ Model [{klass}] column [{column.key}] exists in table [{table}]'
                    )

    return not errors


async def is_sane_database_async(Base, engine: AsyncEngine | AsyncConnection) -> bool:
    """Async variant: check the database against the declared models.

    ``inspect()`` cannot run on an async engine/connection, so the inspection
    runs inside :meth:`AsyncConnection.run_sync`.
    """
    if isinstance(engine, AsyncConnection):
        return await engine.run_sync(_check_models_against_connection, Base)

    async with engine.connect() as conn:
        return await conn.run_sync(_check_models_against_connection, Base)


def is_sane_database(Base, engine) -> bool:
    """Check whether the current database matches the declared models.

    Currently we check that every mapped model has a corresponding table with
    all of its columns. What is *not* checked:

    * Column types are not verified
    * Relationships are not verified at all (TODO)

    :param Base: Declarative base whose ``registry`` holds the models to check.
    :param engine: A sync ``Engine``/``Connection`` or an ``AsyncEngine``.
        ``inspect()`` cannot run on an ``AsyncEngine`` directly, so for the
        async case the check runs via :func:`is_sane_database_async`.
    :return: True if all declared models have matching tables and columns.
    """
    if isinstance(engine, AsyncEngine):
        # Called from a synchronous startup path before the app's event loop
        # exists, so drive the async check with ``asyncio.run`` and dispose the
        # pool afterwards to avoid leaving a connection bound to this
        # short-lived loop (which the app's real loop would later reject).
        async def _run() -> bool:
            try:
                return await is_sane_database_async(Base, engine)
            finally:
                await engine.dispose()

        return asyncio.run(_run())

    if isinstance(engine, Connection):
        return _check_models_against_connection(engine, Base)

    # Plain sync Engine.
    with engine.connect() as conn:
        return _check_models_against_connection(conn, Base)
