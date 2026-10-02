"""
SQL helpers shared by every resiliant repository — the Python twin of
``@taas/resiliant`` ``src/db/index.ts`` + ``src/runtime/index.ts``.

* Timestamps the relays depend on come from the **database clock** (``db_now``).
* Status predicates of claim queries are **inlined literals** (``in_values``) so they
  match the partial indexes literally (a bound parameter would stop the planner
  from using ``*_due_idx``).
"""

from __future__ import annotations

import random
import re
from collections.abc import Callable, Iterable
from typing import Any, Literal

from sqlalchemy import ColumnElement, func, literal_column, text
from sqlalchemy.sql.elements import TextClause

_LITERAL = re.compile(r'^[a-z_][a-z0-9_]*$')
MAX_ERROR_LENGTH = 2000


def db_now() -> ColumnElement[Any]:
    """``now()`` on the database clock (transaction start time)."""
    return func.now()


def interval_ms(ms: float) -> TextClause:
    """``ms`` as a typed Postgres interval (never an ambiguous operator)."""
    return text(f"({max(0, round(ms))}::double precision * interval '1 millisecond')")


def interval_days(days: float) -> TextClause:
    return text(f"({float(days)}::double precision * interval '1 day')")


def db_now_plus_ms(ms: float) -> ColumnElement[Any]:
    return func.now() + interval_ms(ms)


def db_now_minus_ms(ms: float) -> ColumnElement[Any]:
    return func.now() - interval_ms(ms)


def sql_literal(value: str) -> ColumnElement[Any]:
    """``'value'`` inlined (only plain lower-case identifiers: statuses, kinds)."""
    if not _LITERAL.match(value):
        raise ValueError(f'refusing to inline {value!r} into SQL')
    return literal_column(f"'{value}'")


def in_values(column: Any, values: Iterable[str]) -> ColumnElement[bool]:
    """``column in ('a', 'b')`` with inlined literals (matches partial index predicates)."""
    literals = [sql_literal(str(getattr(v, 'value', v))) for v in values]
    if not literals:
        raise ValueError('in_values needs at least one value')
    if len(literals) == 1:
        return column == literals[0]
    return column.in_(literals)


def clip(message: str, max_length: int = MAX_ERROR_LENGTH) -> str:
    """Error text bounded for ``last_error`` columns (same as JS ``clip``: ``max`` chars + ``…``)."""
    return message if len(message) <= max_length else f'{message[:max_length]}…'


def describe_error(error: BaseException) -> str:
    """``Name: message`` (same as JS ``describeError``)."""
    return f'{type(error).__name__}: {error}'


def exponential_backoff_ms(attempt: int, multiplier: float, cap_ms: float) -> float:
    """``multiplier ** attempt`` seconds, capped: attempt 1 → 2 s, 2 → 4 s, … (multiplier 2)."""
    try:
        ms = (multiplier ** max(0, attempt)) * 1000
    except OverflowError:
        return cap_ms
    return min(ms, cap_ms)


def next_idle_sleep_ms(
    strategy: Literal['fixed', 'adaptive', 'notify'] | str,
    *,
    fixed_ms: float,
    min_ms: float,
    max_ms: float,
    growth_factor: float,
    previous_ms: float,
    found: int,
    rand: Callable[[], float] = random.random,
) -> float:
    """Sleep before the next poll: fixed, or decorrelated jitter ``U(min, min(max, prev × growth))``."""
    if strategy == 'fixed':
        return fixed_ms
    if found > 0:
        return min_ms
    upper = max(min_ms, min(max_ms, previous_ms * growth_factor))
    return min_ms + rand() * (upper - min_ms)


__all__ = [
    'MAX_ERROR_LENGTH',
    'clip',
    'db_now',
    'db_now_minus_ms',
    'db_now_plus_ms',
    'describe_error',
    'exponential_backoff_ms',
    'in_values',
    'interval_days',
    'interval_ms',
    'next_idle_sleep_ms',
    'sql_literal',
]
