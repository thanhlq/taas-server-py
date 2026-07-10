from functools import lru_cache
from foundation.config.db_settings import DatabaseSettings


@lru_cache(maxsize=1)
def get_keycloak_db_settings() -> DatabaseSettings:
    """
    Get Keycloak database settings from environment variables.
    """
    return DatabaseSettings(
        prefix='KEYCLOAK_',
    )
