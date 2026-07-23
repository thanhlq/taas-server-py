"""A utility for database consistency checking. It checks that all models are present in the database and that all columns are present in the database."""

from advanced_alchemy.base import AdvancedDeclarativeBase

from db.utils.db_consistency_check import a_run_database_consistency_check

# def check_db_consistency() -> bool:
#     from foundation.db.advanced_db_manager import MainDatabase

#     return is_sane_database(
#         AdvancedDeclarativeBase, MainDatabase.get_instance()._engine
#     )


async def a_check_db_consistency() -> list[str]:
    from foundation.db.advanced_db_manager import MainDatabase

    return await a_run_database_consistency_check(
        AdvancedDeclarativeBase, MainDatabase.get_instance().get_engine()
    )
