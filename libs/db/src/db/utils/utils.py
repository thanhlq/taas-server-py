import datetime
import re
from functools import partial
from typing import Optional, TypeVar

from foundation.utils import now_in_utc

# from sqlmodel import SQLModel

_snake_1 = partial(re.compile(r'(.)((?<![^A-Za-z])[A-Z][a-z]+)').sub, r'\1_\2')
_snake_2 = partial(re.compile(r'([a-z0-9])([A-Z])').sub, r'\1_\2')

OrmModelT = TypeVar('OrmModelT')


def snake_case(string: str) -> str:
    return _snake_2(_snake_1(string)).casefold()


# class DBResult(Generic[OrmModelT]):
#     data: list[OrmModelT]
#     count: Optional[int] = None


def parse_request_paging_params(**kwargs) -> tuple[Optional[int], Optional[int]]:
    """
    Parse pagination parameters from a request.
    Returns a tuple of (limit, offset) where both are optional integers.
    If parameters are missing or invalid, returns (None, None).
    """
    limit = kwargs.pop('limit')
    offset = kwargs.pop('offset')

    try:
        limit = int(limit) if limit is not None else None
        offset = int(offset) if offset is not None else None
    except ValueError:
        limit = None
        offset = None

    return limit, offset


def debug_e(Exception: Exception, message: str = '') -> None:
    """
    A utility function to print debug information about an exception.
    """
    print(f'Exception: {type(Exception).__name__}')
    if message:
        print(f'Message: {message}')
    print(f'Args: {Exception.args}')
    print(f'Traceback: {Exception.__traceback__}')
    print(f'String representation: {str(Exception)}')


class DBUtils:
    @staticmethod
    def now() -> datetime.datetime:
        # used for filling dtimetime
        return now_in_utc().replace(tzinfo=None)

    @staticmethod
    def chunk_list(data: list, chunk_size: int) -> list[list]:
        """
        Split a list into smaller chunks of specified size.
        Examples:
        >>> DataUtils.chunk_list([1, 2, 3, 4, 5], 2)
        [[1, 2], [3, 4], [5]]
        """
        return [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]
