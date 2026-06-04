from .fastapi_app import create_app
from .middewares.fastapi_cache import initFastapiCache

__all__ = [
    'create_app',
    'initFastapiCache',
]
