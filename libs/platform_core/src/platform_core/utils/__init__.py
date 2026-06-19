from .env_utils import get_env


def get_env_int(key: str, default: int) -> int:
    return get_env(key, default, int)


def get_env_bool(key: str, default: bool) -> bool:
    return get_env(key, default, bool)


__all__ = [
    'get_env',
    'get_env_int',
    'get_env_bool',
]
