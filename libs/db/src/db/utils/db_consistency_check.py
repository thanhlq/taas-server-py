import asyncio
import logging
from typing import List, Union

from sqlalchemy import inspect
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from sqlalchemy.orm import RelationshipProperty


def _declared_columns(mapper) -> List[str]:
    """Return the keys of the flat columns declared on a mapped class.

    Relationship properties are skipped (they don't map to physical columns);
    each remaining property may expand to one or more columns.
    """
    keys: List[str] = []
    for column_prop in mapper.attrs:
        if isinstance(column_prop, RelationshipProperty):
            # TODO: Add sanity checks for relations
            continue
        for column in column_prop.columns:
            keys.append(column.key)
    return keys


def _check_relation_columns(
    iengine,
    logger,
    klass,
    relation: str,
    kind: str,
    declared_columns: List[str],
    err_messages: List[str],
) -> bool:
    """Check every declared column of ``klass`` exists in ``relation``.

    ``kind`` is a human label (``'table'`` / ``'view'``) used only in messages.
    Appends to ``err_messages`` and returns ``True`` when an error was found.
    """
    # get_columns() works for both tables and views. It looks like:
    #   [{'name': 'id', 'type': INTEGER(), 'nullable': False, ...}]
    columns = {c['name'] for c in iengine.get_columns(relation)}

    errors = False
    for column_key in declared_columns:
        if column_key not in columns:
            _err = (
                f'🐘 ❌ Model {klass} declares column {column_key} '
                f'which does not exist in {kind} {relation}'
            )
            err_messages.append(_err)
            logger.error(_err)
            errors = True
    return errors


def _check_extra_db_columns(
    iengine,
    logger,
    klass,
    relation: str,
    kind: str,
    declared_columns: List[str],
    err_messages: List[str],
) -> bool:
    """Check ``relation`` has no columns that ``klass`` does not declare.

    The inverse of :func:`_check_relation_columns`: it flags physical columns
    present in the table/view but not mapped on the model — i.e. schema drift
    the ORM is unaware of (a column added by a migration but never added to the
    model). ``kind`` is a human label (``'table'`` / ``'view'``) used only in
    messages. Appends to ``err_messages`` and returns ``True`` when an error was
    found.
    """
    db_columns = {c['name'] for c in iengine.get_columns(relation)}
    declared = set(declared_columns)

    errors = False
    # Sorted for stable, deterministic message ordering.
    for column_name in sorted(db_columns - declared):
        _err = (
            f'🐘 ⚠️ {kind.capitalize()} {relation} has column {column_name} '
            f'which is not declared on model {klass}'
        )
        # err_messages.append(_err)
        logger.warning(_err)
        errors = True
    return errors


def _check_models_against_connection(
    connection: Connection, Base, check_extra_db_columns: bool = False
) -> List[str]:
    """Consistency-check body, run against a *sync* :class:`Connection`.

    ``inspect()`` only accepts a sync ``Connection``/``Engine``; async callers
    obtain one via :meth:`AsyncConnection.run_sync`.

    - Checking if a table or view exists for each model
    - Checking if each declared column exists in the table/view
    - When ``check_extra_db_columns`` is True, also checking the opposite
      direction: that each column present in a model's table/view is declared
      on the model (i.e. no undeclared/orphan columns).
    """
    logger = logging.getLogger()
    logger.info('🐘 Starting database consistency check...')
    # The purpose is to collect and print errors at the end, but we also log them as they occur.
    _err_messages: List[str] = []

    iengine = inspect(connection)

    tables = set(iengine.get_table_names())
    views = set(iengine.get_view_names())

    # SQLAlchemy 2.0: iterate the mapped classes via the registry. The old
    # ``Base._decl_class_registry`` (and its ``_ModuleMarker`` entries) was
    # removed in 1.4+, so ``registry.mappers`` is the supported replacement.
    for mapper in Base.registry.mappers:
        klass = mapper.class_

        # Keycloak models share advanced_alchemy's global registry, but their
        # tables live in the separate Keycloak-managed database (not the main
        # application DB), so they must not be validated here.
        if 'keycloak' in klass.__module__:
            logger.debug(f'🐘 Skipping Keycloak model {klass} (external database)')
            continue

        relation = klass.__tablename__

        # Resolve whether the model maps to a table or a view (or neither).
        if relation in tables:
            kind = 'table'
        elif relation in views:
            kind = 'view'
        else:
            _m = f'🐘 ❌ Model {klass} declares table/view {relation} which does not exist in the database'

            _err_messages.append(_m)
            logger.error(_m)
            continue

        logger.info(f'🐘 Checking model [{klass}] with {kind} [{relation}]...')

        declared_columns = _declared_columns(mapper)

        # Forward check: every column declared on the model exists in the DB.
        _check_relation_columns(
            iengine,
            logger,
            klass,
            relation,
            kind,
            declared_columns,
            _err_messages,
        )

        # Reverse check (opt-in): every column in the DB relation is declared
        # on the model — catches schema drift the ORM is unaware of.
        if check_extra_db_columns:
            _check_extra_db_columns(
                iengine,
                logger,
                klass,
                relation,
                kind,
                declared_columns,
                _err_messages,
            )
    # Print all errors at the end, if any
    if _err_messages and len(_err_messages) > 0:
        logger.error(
            f'🐘 Database consistency check FAILED, found {len(_err_messages)} errors:\n'
            + '\n'.join(_err_messages)
        )
    else:
        logger.info('🐘 ✅ Database consistency check with OK result!')

    return _err_messages


async def a_run_database_consistency_check(
    Base,
    engine: Union[AsyncEngine, AsyncConnection],
    check_extra_db_columns: bool = True,
) -> List[str]:
    """Async variant: check the database against the declared models.

    ``inspect()`` cannot run on an async engine/connection, so the inspection
    runs inside :meth:`AsyncConnection.run_sync`.

    :param check_extra_db_columns: when True, also flag columns that exist in
        the database but are not declared on the corresponding model.
    """
    if isinstance(engine, AsyncConnection):
        return await engine.run_sync(
            _check_models_against_connection, Base, check_extra_db_columns
        )

    async with engine.connect() as conn:
        return await conn.run_sync(
            _check_models_against_connection, Base, check_extra_db_columns
        )


def run_database_consistency_check(
    Base, engine, check_extra_db_columns: bool = True
) -> List[str]:
    """Check the database against the declared models.

    :param check_extra_db_columns: when True, also flag columns that exist in
        the database but are not declared on the corresponding model.
    """
    if isinstance(engine, AsyncEngine):

        async def _run() -> List[str]:
            try:
                return await a_run_database_consistency_check(
                    Base, engine, check_extra_db_columns
                )
            finally:
                await engine.dispose()

        # Run in the current asyncio event loop if one exists, otherwise create a new one.
        try:
            loop = asyncio.get_running_loop()
            return loop.run_until_complete(_run())
        except RuntimeError:
            return asyncio.run(_run())

    if isinstance(engine, Connection):
        return _check_models_against_connection(
            engine, Base, check_extra_db_columns
        )

    # Plain sync Engine.
    with engine.connect() as conn:
        return _check_models_against_connection(
            conn, Base, check_extra_db_columns
        )


__all__ = [
    'run_database_consistency_check',
    'a_run_database_consistency_check',
]
