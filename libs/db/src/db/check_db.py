"""A utility for database consistency checking. It checks that all models are present in the database and that all columns are present in the database."""

from advanced_alchemy.base import AdvancedDeclarativeBase

from db.utils.db_consistency_check import is_sane_database


def check_db_consistency() -> bool:
    from foundation.db.advanced_db_manager import MainDatabase

    return is_sane_database(
        AdvancedDeclarativeBase, MainDatabase.get_instance()._engine
    )
