from __future__ import annotations

import re
from dataclasses import dataclass
from io import StringIO
from typing import TYPE_CHECKING, AsyncGenerator, AsyncIterable, AsyncIterator, Iterable, Iterator


DEFAULT_SEPARATOR = "\r\n"

@dataclass
class ServerSentEventMessage:
    data: str | int | bytes | None = ""
    event: str | None = None
    id: int | str | None = None
    retry: int | None = None
    comment: str | None = None
    sep: str = DEFAULT_SEPARATOR
