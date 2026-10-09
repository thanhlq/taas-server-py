"""CSV exports of PPM lists (Ppm-0014; Excel / PDF later): projects and a project's items. UTF-8 with a BOM so
spreadsheets open accents correctly; formula-looking cells are prefixed with ``'`` (CSV injection)."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from typing import Any

DANGEROUS = ('=', '+', '-', '@', '\t', '\r')


def _cell(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, datetime):
        text = (
            value.date().isoformat()
            if value.time() == datetime.min.time()
            else value.isoformat()
        )
    elif isinstance(value, date):
        text = value.isoformat()
    elif isinstance(value, (list, tuple)):
        text = ', '.join(str(v) for v in value)
    else:
        text = str(value)
    return f"'{text}" if text.startswith(DANGEROUS) else text


def to_csv(header: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    for row in rows:
        writer.writerow([_cell(v) for v in row])
    return '﻿' + out.getvalue()
